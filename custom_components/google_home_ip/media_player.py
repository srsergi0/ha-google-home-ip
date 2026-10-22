"""Entidad media_player de Google Home IP."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

from homeassistant.components import media_source
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    DEFAULT_MIME_TYPE,
    DOMAIN,
    LOGGER,
    MIME_TYPES,
    RESTORE_MAX_WAIT,
    RESTORE_START_TIMEOUT,
)
from .device import GoogleHomeConfigEntry, GoogleHomeDevice

PARALLEL_UPDATES = 0

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.BROWSE_MEDIA
)

_PLAYER_STATES: dict[str, MediaPlayerState] = {
    "PLAYING": MediaPlayerState.PLAYING,
    "BUFFERING": MediaPlayerState.BUFFERING,
    "PAUSED": MediaPlayerState.PAUSED,
}

_ACTIVE_STATES = (
    MediaPlayerState.PLAYING,
    MediaPlayerState.BUFFERING,
    MediaPlayerState.PAUSED,
)


def guess_mime_type(url: str) -> str:
    """Tipo MIME según la extensión (mp3, wav, ogg, aac, flac)."""
    suffix = PurePosixPath(urlparse(url).path).suffix.lower()
    return MIME_TYPES.get(suffix, DEFAULT_MIME_TYPE)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea la entidad media_player del dispositivo."""
    async_add_entities([GoogleHomeMediaPlayer(entry.runtime_data, entry.entry_id)])


class GoogleHomeMediaPlayer(MediaPlayerEntity):
    """Google Home controlado directamente por IP."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_supported_features = SUPPORTED_FEATURES
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, device: GoogleHomeDevice, entry_id: str) -> None:
        """Inicializa la entidad."""
        self._device = device
        self._attr_unique_id = entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=device.name,
            manufacturer="Google",
            model="Google Home",
        )
        self._restore_task: asyncio.Task[None] | None = None
        self._volume_to_restore: float | None = None
        self._device_changed = asyncio.Event()

    async def async_added_to_hass(self) -> None:
        """Se suscribe a los cambios del dispositivo."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._device.signal, self._async_device_updated
            )
        )
        self.async_on_remove(self._cancel_restore)

    @callback
    def _async_device_updated(self) -> None:
        self._update_device_info()
        self.async_write_ha_state()
        self._device_changed.set()

    @callback
    def _update_device_info(self) -> None:
        """Completa la ficha del dispositivo cuando se conoce el modelo."""
        info = self._device.cast_info
        if (
            info is None
            or self.registry_entry is None
            or not self.registry_entry.device_id
        ):
            return
        registry = dr.async_get(self.hass)
        device_entry = registry.async_get(self.registry_entry.device_id)
        if device_entry is None:
            return
        model = info.model_name or "Google Home"
        manufacturer = info.manufacturer or "Google"
        if device_entry.model != model or device_entry.manufacturer != manufacturer:
            registry.async_update_device(
                device_entry.id, model=model, manufacturer=manufacturer
            )

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """No disponible si el Google Home no responde."""
        return self._device.connected

    @property
    def state(self) -> MediaPlayerState:
        """Reproduciendo, en pausa o inactivo."""
        status = self._device.media_status
        if status is None:
            return MediaPlayerState.IDLE
        return _PLAYER_STATES.get(status.player_state, MediaPlayerState.IDLE)

    @property
    def volume_level(self) -> float | None:
        """Volumen actual (0-1)."""
        return self._device.volume_level

    @property
    def is_volume_muted(self) -> bool | None:
        """Indica si está silenciado."""
        status = self._device.cast_status
        return status.volume_muted if status else None

    @property
    def app_name(self) -> str | None:
        """Aplicación Cast activa."""
        status = self._device.cast_status
        return status.display_name if status else None

    @property
    def media_content_id(self) -> str | None:
        """URL del audio actual."""
        status = self._device.media_status
        return status.content_id if status else None

    @property
    def media_title(self) -> str | None:
        """Título del audio actual."""
        status = self._device.media_status
        return status.title if status else None

    @property
    def media_artist(self) -> str | None:
        """Artista del audio actual."""
        status = self._device.media_status
        return status.artist if status else None

    @property
    def media_image_url(self) -> str | None:
        """Carátula del audio actual."""
        status = self._device.media_status
        if status is None or not status.images:
            return None
        return status.images[0].url

    @property
    def media_duration(self) -> float | None:
        """Duración en segundos."""
        status = self._device.media_status
        return status.duration if status else None

    @property
    def media_position(self) -> float | None:
        """Posición en segundos."""
        status = self._device.media_status
        if status is None or self.state not in _ACTIVE_STATES:
            return None
        return status.current_time

    @property
    def media_position_updated_at(self) -> datetime | None:
        """Momento de la última actualización de la posición."""
        if self.media_position is None:
            return None
        return self._device.media_status_received

    # ------------------------------------------------------------------
    # Controles
    # ------------------------------------------------------------------

    async def async_media_play(self) -> None:
        """Reanuda."""
        await self.hass.async_add_executor_job(self._device.play)

    async def async_media_pause(self) -> None:
        """Pausa."""
        await self.hass.async_add_executor_job(self._device.pause)

    async def async_media_stop(self) -> None:
        """Detiene."""
        await self.hass.async_add_executor_job(self._device.stop)

    async def async_set_volume_level(self, volume: float) -> None:
        """Fija el volumen."""
        await self.hass.async_add_executor_job(self._device.set_volume, volume)

    async def async_volume_up(self) -> None:
        """Sube el volumen."""
        await self.hass.async_add_executor_job(self._device.volume_up, self.volume_step)

    async def async_volume_down(self) -> None:
        """Baja el volumen."""
        await self.hass.async_add_executor_job(
            self._device.volume_down, self.volume_step
        )

    async def async_mute_volume(self, mute: bool) -> None:
        """Silencia o reactiva."""
        await self.hass.async_add_executor_job(self._device.set_muted, mute)

    async def async_browse_media(
        self,
        media_content_type: MediaType | str | None = None,
        media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Explorador multimedia (Media Source), filtrado a audio."""
        return await media_source.async_browse_media(
            self.hass,
            media_content_id,
            content_filter=lambda item: item.media_content_type.startswith("audio/"),
        )

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Reproduce una URL o un elemento de Media Source (incluido TTS)."""
        mime_type: str | None = None

        if media_source.is_media_source_id(media_id):
            play_item = await media_source.async_resolve_media(
                self.hass, media_id, self.entity_id
            )
            media_id = play_item.url
            mime_type = play_item.mime_type

        media_id = async_process_play_media_url(self.hass, media_id)

        if not mime_type or "/" not in mime_type:
            # media_type suele ser "music"/"audio" y no un MIME real.
            mime_type = (
                media_type if "/" in str(media_type) else guess_mime_type(media_id)
            )

        extra: dict[str, Any] = kwargs.get("extra") or {}
        title: str | None = extra.get("title")

        await self.hass.async_add_executor_job(
            self._device.play_media, media_id, str(mime_type), title
        )

    # ------------------------------------------------------------------
    # Servicio google_home_ip.play_audio
    # ------------------------------------------------------------------

    async def async_play_audio(
        self, media: str, volume: float | None = None, restore_volume: bool = False
    ) -> None:
        """Reproduce una URL o una ruta local de /config/www."""
        url, mime_type = await self._async_resolve_audio(media)

        if restore_volume and self._volume_to_restore is None:
            # Si ya hay una restauración pendiente se conserva el volumen original.
            self._volume_to_restore = self._device.volume_level
        self._cancel_restore()

        if volume is not None:
            await self.async_set_volume_level(volume)

        await self.hass.async_add_executor_job(
            self._device.play_media, url, mime_type, None
        )

        if restore_volume and self._volume_to_restore is not None:
            self._restore_task = self.hass.async_create_background_task(
                self._async_restore_volume_when_done(),
                f"{DOMAIN} restaurar volumen {self.entity_id}",
            )
        else:
            self._volume_to_restore = None

    async def _async_resolve_audio(self, media: str) -> tuple[str, str]:
        """Convierte el parámetro media en una URL accesible y su tipo MIME."""
        media = media.strip()

        if media_source.is_media_source_id(media):
            play_item = await media_source.async_resolve_media(
                self.hass, media, self.entity_id
            )
            url = async_process_play_media_url(self.hass, play_item.url)
            return url, play_item.mime_type or guess_mime_type(url)

        if urlparse(media).scheme in ("http", "https"):
            return media, guess_mime_type(media)

        relative = await self.hass.async_add_executor_job(self._local_www_path, media)
        try:
            base_url = get_url(self.hass, allow_external=False)
        except NoURLAvailableError:
            LOGGER.warning(
                "No hay URL interna configurada; se usará la URL disponible. "
                "Configúrala en Ajustes > Sistema > Red"
            )
            try:
                base_url = get_url(self.hass)
            except NoURLAvailableError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="no_url"
                ) from err

        url = f"{base_url}/local/{quote(relative.as_posix())}"
        LOGGER.debug("Ruta local %s convertida a %s", media, url)
        return url, guess_mime_type(url)

    def _local_www_path(self, media: str) -> PurePosixPath:
        """Valida una ruta local y la devuelve relativa a /config/www.

        Acepta ``/config/www/x.mp3``, ``/local/x.mp3`` y ``x.mp3`` (relativa a www).
        """
        www = Path(self.hass.config.path("www")).resolve()
        if media.startswith("/local/"):
            candidate = www / media.removeprefix("/local/")
        elif Path(media).is_absolute():
            candidate = Path(media)
        else:
            candidate = www / media

        resolved = candidate.resolve()
        if not resolved.is_relative_to(www):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="path_not_allowed",
                translation_placeholders={"path": media, "www": str(www)},
            )
        if not resolved.is_file():
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="file_not_found",
                translation_placeholders={"path": str(resolved)},
            )
        return PurePosixPath(resolved.relative_to(www).as_posix())

    async def _async_wait_until(self, predicate: Callable[[], bool]) -> None:
        """Espera a que se cumpla la condición tras un cambio de estado."""
        while not predicate():
            self._device_changed.clear()
            await self._device_changed.wait()

    @callback
    def _cancel_restore(self) -> None:
        if self._restore_task is not None:
            self._restore_task.cancel()
            self._restore_task = None

    async def _async_restore_volume_when_done(self) -> None:
        """Espera a que termine el audio y restaura el volumen anterior."""
        previous = self._volume_to_restore
        try:
            async with asyncio.timeout(RESTORE_START_TIMEOUT):
                await self._async_wait_until(lambda: self.state in _ACTIVE_STATES)
            LOGGER.debug(
                "Audio iniciado en %s; esperando a que termine", self.entity_id
            )
        except TimeoutError:
            LOGGER.debug("El audio no llegó a empezar en %s", self.entity_id)

        try:
            async with asyncio.timeout(RESTORE_MAX_WAIT):
                await self._async_wait_until(
                    lambda: not self.available or self.state not in _ACTIVE_STATES
                )
        except TimeoutError:
            LOGGER.warning("Tiempo máximo de espera agotado en %s", self.entity_id)

        self._volume_to_restore = None
        self._restore_task = None
        if previous is None or not self.available:
            return
        LOGGER.info("Restaurando volumen de %s a %.2f", self.entity_id, previous)
        try:
            await self.async_set_volume_level(previous)
        except HomeAssistantError as err:
            LOGGER.error(
                "No se pudo restaurar el volumen de %s: %s", self.entity_id, err
            )
