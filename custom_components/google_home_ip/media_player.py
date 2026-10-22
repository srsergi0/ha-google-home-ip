"""Entidad media_player de Google Home IP."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

from pychromecast.config import APP_BACKDROP, APP_MEDIA_RECEIVER

from homeassistant.components import media_source, tts
from homeassistant.components.media_player import (
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    async_process_play_media_url,
)
from homeassistant.components.media_player.const import ATTR_MEDIA_ANNOUNCE
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import (
    CHIME_NONE,
    CHIMES_URL,
    CONF_BASE_URL,
    CONF_LANGUAGE,
    CONF_TTS_ENTITY,
    DEFAULT_FADE_OUT,
    DEFAULT_MIME_TYPE,
    DEVICE_EVENT,
    DOMAIN,
    EVENT_ANNOUNCEMENT_FINISHED,
    EVENT_ANNOUNCEMENT_STARTED,
    EVENT_PLAYBACK_ERROR,
    EVENT_PLAYBACK_FINISHED,
    EVENT_SLEEP_TIMER_FINISHED,
    FADE_ABORT_DELTA,
    FADE_MAX_STEPS,
    FADE_MIN_INTERVAL,
    LOGGER,
    MIME_TYPES,
    RESTORE_MAX_WAIT,
    RESTORE_START_TIMEOUT,
    SIGNAL_EVENT,
    SIGNAL_SETTINGS,
)
from .device import GoogleHomeDevice
from .entity import GoogleHomeEntity
from .models import GoogleHomeConfigEntry

PARALLEL_UPDATES = 0

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
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

# Apps que equivalen a "apagado": ninguna o el fondo de pantalla.
_IDLE_APPS = (None, APP_BACKDROP)


@dataclass(frozen=True, slots=True)
class _MediaSnapshot:
    """Audio del Default Media Receiver que se reanuda tras un aviso."""

    url: str
    content_type: str
    title: str | None
    stream_type: str
    position: float | None
    autoplay: bool


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
    async_add_entities([GoogleHomeMediaPlayer(entry)])


class GoogleHomeMediaPlayer(GoogleHomeEntity, MediaPlayerEntity):
    """Google Home controlado directamente por IP."""

    _attr_name = None
    _attr_should_poll = False
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, entry: GoogleHomeConfigEntry) -> None:
        """Inicializa la entidad."""
        super().__init__(entry)
        self._entry = entry
        self._device: GoogleHomeDevice = entry.runtime_data.device
        self._attr_unique_id = entry.entry_id
        self._restore_task: asyncio.Task[None] | None = None
        self._volume_to_restore: float | None = None
        self._media_to_resume: _MediaSnapshot | None = None
        self._device_changed = asyncio.Event()

        # Avisos en cola: cada llamada a announce espera a la anterior.
        self._announce_lock = asyncio.Lock()
        self._announcing = False
        self._fade_task: asyncio.Task[None] | None = None
        self._sleep_task: asyncio.Task[None] | None = None
        self._sleep_finishing = False
        self._loop_url: str | None = None
        # Para emitir cada fin de reproducción y cada error una sola vez.
        self._last_idle_key: tuple[Any, str] | None = None
        self._load_failures = self._device.load_failures
        self._last_error_at = 0.0
        self._device_id: str | None = None

    async def async_added_to_hass(self) -> None:
        """Se suscribe a los cambios del dispositivo."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._device.signal, self._async_device_updated
            )
        )
        self.async_on_remove(self._cancel_restore)
        self.async_on_remove(self._cancel_fade)
        self.async_on_remove(lambda: self._cancel_sleep_timer(notify=False))
        registry = dr.async_get(self.hass)
        identifier = (DOMAIN, self._entry.entry_id)
        if hasattr(registry, "async_get_device_by_identifier"):
            device = registry.async_get_device_by_identifier(
                identifier, self._entry.entry_id
            )
        else:
            device = registry.async_get_device(identifiers={identifier})
        self._device_id = device.id if device else None

    @callback
    def _async_device_updated(self) -> None:
        self._async_check_playback_end()
        if self.state == MediaPlayerState.OFF:
            # Si alguien apaga el altavoz, no hay nada que repetir ni que apagar.
            self._loop_url = None
            if self._sleep_task is not None and not self._sleep_finishing:
                self._cancel_sleep_timer()
        self.async_write_ha_state()
        self._device_changed.set()

    @callback
    def _async_check_playback_end(self) -> None:
        """Emite los eventos de fin de reproducción y de error."""
        if self._device.load_failures != self._load_failures:
            self._load_failures = self._device.load_failures
            self._fire_error(self.media_content_id)

        status = self._device.media_status
        if status is None or status.player_state != "IDLE" or not status.idle_reason:
            return
        key = (status.media_session_id, status.idle_reason)
        if key == self._last_idle_key:
            return
        self._last_idle_key = key
        if self._announcing:
            # Las piezas de un aviso (campanita, voz) no cuentan por separado.
            return

        url = status.content_id
        if status.idle_reason == "FINISHED":
            if self._loop_url is not None and url == self._loop_url:
                self.hass.async_create_task(self._async_replay_loop(status))
                return
            self._fire(EVENT_PLAYBACK_FINISHED, {"media": url})
        elif status.idle_reason == "ERROR":
            self._fire_error(url)
        elif status.idle_reason == "CANCELLED":
            self._loop_url = None

    @callback
    def _fire(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Envía un evento a la entidad event del dispositivo."""
        payload = {"entity_id": self.entity_id, **(data or {})}
        async_dispatcher_send(
            self.hass, SIGNAL_EVENT.format(self._entry.entry_id), event_type, payload
        )
        self.hass.bus.async_fire(
            DEVICE_EVENT,
            {"device_id": self._device_id, "type": event_type, **payload},
        )

    @callback
    def _fire_error(self, url: str | None) -> None:
        # El altavoz puede informar del mismo fallo por dos vías seguidas.
        now = self.hass.loop.time()
        if now - self._last_error_at > 3:
            self._fire(EVENT_PLAYBACK_ERROR, {"media": url})
        self._last_error_at = now

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """No disponible si el Google Home no responde."""
        return self._device.connected

    @property
    def state(self) -> MediaPlayerState:
        """Apagado (sin app Cast), reproduciendo, en pausa o inactivo."""
        cast_status = self._device.cast_status
        if cast_status is not None and cast_status.app_id in _IDLE_APPS:
            return MediaPlayerState.OFF
        status = self._device.media_status
        if status is None:
            return MediaPlayerState.IDLE
        return _PLAYER_STATES.get(status.player_state, MediaPlayerState.IDLE)

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Añade seek y siguiente/anterior cuando la app activa los admite."""
        features = SUPPORTED_FEATURES
        status = self._device.media_status
        if status is None or self.state not in _ACTIVE_STATES:
            return features
        if status.supports_seek:
            features |= MediaPlayerEntityFeature.SEEK
        if status.supports_queue_next:
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if status.supports_queue_prev:
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        return features

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
        self._loop_url = None
        await self.hass.async_add_executor_job(self._device.stop)

    async def async_media_seek(self, position: float) -> None:
        """Salta a una posición."""
        await self.hass.async_add_executor_job(self._device.seek, position)

    async def async_media_next_track(self) -> None:
        """Siguiente."""
        await self.hass.async_add_executor_job(self._device.next_track)

    async def async_media_previous_track(self) -> None:
        """Anterior."""
        await self.hass.async_add_executor_job(self._device.previous_track)

    async def async_turn_on(self) -> None:
        """Abre el Default Media Receiver."""
        await self.hass.async_add_executor_job(self._device.turn_on)

    async def async_turn_off(self) -> None:
        """Cierra la app activa."""
        self._cancel_restore()
        self._cancel_fade()
        self._cancel_sleep_timer()
        self._volume_to_restore = None
        self._media_to_resume = None
        self._loop_url = None
        await self.hass.async_add_executor_job(self._device.turn_off)

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

        media_id = self._absolute_url(media_id)

        if not mime_type or "/" not in mime_type:
            # media_type suele ser "music"/"audio" y no un MIME real.
            mime_type = (
                media_type if "/" in str(media_type) else guess_mime_type(media_id)
            )

        extra: dict[str, Any] = kwargs.get("extra") or {}
        title: str | None = extra.get("title")

        await self._async_play(
            media_id,
            str(mime_type),
            title,
            announce=bool(kwargs.get(ATTR_MEDIA_ANNOUNCE)),
        )

    # ------------------------------------------------------------------
    # Servicio google_home_ip.play_audio
    # ------------------------------------------------------------------

    async def async_play_audio(
        self,
        *,
        media: str,
        volume: float | None = None,
        restore_volume: bool = False,
        announce: bool = False,
        loop: bool = False,
        fade_in: float | None = None,
    ) -> None:
        """Reproduce una URL o una ruta local de /config/www."""
        url, mime_type = await self._async_resolve_audio(media)
        self._loop_url = url if loop else None
        if fade_in:
            # Empieza en silencio y sube hasta el volumen pedido (o el actual).
            target = volume if volume is not None else self._device.volume_level
            await self.async_set_volume_level(0.0)
            await self._async_play(url, mime_type, None, announce=announce)
            if target:
                self._schedule_fade(target, fade_in)
            return
        await self._async_play(
            url,
            mime_type,
            None,
            volume=volume,
            restore_volume=restore_volume,
            announce=announce,
        )

    async def _async_play(
        self,
        url: str,
        mime_type: str,
        title: str | None,
        *,
        volume: float | None = None,
        restore_volume: bool = False,
        announce: bool = False,
    ) -> None:
        """Reproduce y programa la restauración de volumen y del audio previo.

        Si ya hay una restauración pendiente (un aviso encima de otro) se
        conservan el volumen y el audio originales.
        """
        if restore_volume and self._volume_to_restore is None:
            self._volume_to_restore = self._device.volume_level
        if announce and self._media_to_resume is None:
            self._media_to_resume = self._snapshot_media()
        pending = self._restore_task is not None
        self._cancel_restore()

        if volume is not None:
            await self.async_set_volume_level(volume)

        await self.hass.async_add_executor_job(
            self._device.play_media, url, mime_type, title
        )

        if not (restore_volume or announce or pending):
            # Reproducción normal: descarta lo que quedara pendiente.
            self._volume_to_restore = None
            self._media_to_resume = None
            return
        if self._volume_to_restore is None and self._media_to_resume is None:
            return
        self._restore_task = self.hass.async_create_background_task(
            self._async_restore_when_done(url),
            f"{DOMAIN} restaurar tras aviso {self.entity_id}",
        )

    def _snapshot_media(self) -> _MediaSnapshot | None:
        """Guarda el audio del Default Media Receiver para reanudarlo.

        Solo se puede reanudar lo que reproduce el receptor genérico (radio,
        archivos, TTS...). Apps como Spotify o YouTube no se pueden recuperar.
        """
        cast_status = self._device.cast_status
        status = self._device.media_status
        if (
            cast_status is None
            or cast_status.app_id != APP_MEDIA_RECEIVER
            or status is None
            or not status.content_id
            or self.state not in _ACTIVE_STATES
        ):
            return None
        live = status.stream_type_is_live or not status.duration
        snapshot = _MediaSnapshot(
            url=status.content_id,
            content_type=status.content_type or guess_mime_type(status.content_id),
            title=status.title,
            stream_type="LIVE" if live else "BUFFERED",
            position=None if live else status.adjusted_current_time,
            autoplay=self.state != MediaPlayerState.PAUSED,
        )
        LOGGER.debug("Audio a reanudar tras el aviso: %s", snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # Servicio google_home_ip.announce
    # ------------------------------------------------------------------

    async def async_announce(
        self,
        *,
        message: str | None = None,
        media: str | None = None,
        chime: str | None = None,
        volume: float | None = None,
        tts_entity: str | None = None,
        language: str | None = None,
        resume: bool = True,
        fade_in: float | None = None,
    ) -> None:
        """Da un aviso: campanita opcional, luego voz o audio, y reanuda.

        Encola los avisos (si llega otro mientras suena este, espera su turno)
        y usa el volumen automático día/noche si no se indica ``volume``.
        """
        if not message and not media:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="announce_empty"
            )

        chime_url = self._chime_url(chime)
        voice_url, voice_mime = await self._async_announce_audio(
            message, media, tts_entity, language
        )
        if volume is None:
            volume = self._entry.runtime_data.settings.announce_volume()

        async with self._announce_lock:
            snapshot = self._snapshot_media() if resume else None
            previous_volume = self._device.volume_level if resume else None
            self._cancel_restore()
            self._fire(EVENT_ANNOUNCEMENT_STARTED, {"message": message})
            self._announcing = True
            try:
                if fade_in:
                    await self.async_set_volume_level(0.0)
                elif volume is not None:
                    await self.async_set_volume_level(volume)
                if fade_in and volume:
                    self._schedule_fade(volume, fade_in)
                if chime_url:
                    await self._async_play_and_wait(chime_url, "audio/mpeg")
                await self._async_play_and_wait(voice_url, voice_mime)
            finally:
                self._announcing = False
            self._fire(EVENT_ANNOUNCEMENT_FINISHED, {"message": message})
            await self._async_after_announce(previous_volume, snapshot)

    async def _async_after_announce(
        self, previous_volume: float | None, snapshot: _MediaSnapshot | None
    ) -> None:
        """Restaura el volumen y reanuda el audio previo tras un aviso."""
        if not self.available:
            return
        if previous_volume is not None:
            await self.async_set_volume_level(previous_volume)
        if snapshot is None:
            return
        LOGGER.info("Reanudando %s en %s", snapshot.url, self.entity_id)
        await self.hass.async_add_executor_job(
            lambda: self._device.play_media(
                snapshot.url,
                snapshot.content_type,
                snapshot.title,
                stream_type=snapshot.stream_type,
                current_time=snapshot.position,
                autoplay=snapshot.autoplay,
            )
        )

    async def _async_play_and_wait(self, url: str, mime_type: str) -> None:
        """Reproduce un tramo del aviso y espera a que termine."""
        await self.hass.async_add_executor_job(
            self._device.play_media, url, mime_type, None
        )

        def finished() -> bool:
            status = self._device.media_status
            return not self.available or (
                status is not None
                and status.content_id == url
                and status.player_state == "IDLE"
                and status.idle_reason is not None
            )

        try:
            async with asyncio.timeout(RESTORE_START_TIMEOUT):
                await self._async_wait_until(
                    lambda: not self.available or self._playing(url)
                )
            async with asyncio.timeout(RESTORE_MAX_WAIT):
                await self._async_wait_until(finished)
        except TimeoutError:
            LOGGER.warning("El aviso no terminó a tiempo en %s", self.entity_id)

    def _playing(self, url: str) -> bool:
        status = self._device.media_status
        return (
            status is not None
            and status.content_id == url
            and self.state in _ACTIVE_STATES
        )

    async def _async_announce_audio(
        self,
        message: str | None,
        media: str | None,
        tts_entity: str | None,
        language: str | None,
    ) -> tuple[str, str]:
        """Resuelve el audio del aviso: TTS del mensaje o un medio concreto."""
        if message:
            engine = (
                tts_entity
                or self._entry.options.get(CONF_TTS_ENTITY)
                or tts.async_resolve_engine(self.hass, None)
            )
            if not engine:
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="no_tts"
                )
            media_id = tts.generate_media_source_id(
                self.hass,
                message,
                engine=engine,
                language=language or self._entry.options.get(CONF_LANGUAGE),
            )
            return await self._async_resolve_audio(media_id)
        return await self._async_resolve_audio(media or "")

    def _chime_url(self, chime: str | None) -> str | None:
        """URL absoluta de la campanita, o None si no se quiere."""
        name = chime if chime is not None else self._entry.options.get("chime")
        if not name or name == CHIME_NONE:
            return None
        return f"{self._base_url()}{CHIMES_URL}/{name}.mp3"

    # ------------------------------------------------------------------
    # Servicio google_home_ip.fade_volume
    # ------------------------------------------------------------------

    async def async_fade_volume(self, *, volume: float, duration: float) -> None:
        """Lleva el volumen al valor indicado a lo largo de ``duration`` s."""
        self._cancel_fade()
        await self._async_fade_to(volume, duration)

    def _schedule_fade(self, volume: float, duration: float) -> None:
        self._cancel_fade()
        self._fade_task = self.hass.async_create_background_task(
            self._async_fade_to(volume, duration), f"{DOMAIN} fade {self.entity_id}"
        )

    async def _async_fade_to(self, target: float, duration: float) -> None:
        """Interpola el volumen. Se detiene si alguien lo cambia a mano."""
        target = max(0.0, min(1.0, target))
        start = self._device.volume_level
        if start is None:
            await self.async_set_volume_level(target)
            return
        steps = max(1, min(FADE_MAX_STEPS, int(duration / FADE_MIN_INTERVAL)))
        interval = duration / steps
        expected = start
        try:
            for step in range(1, steps + 1):
                await asyncio.sleep(interval)
                current = self._device.volume_level
                if current is not None and abs(current - expected) > FADE_ABORT_DELTA:
                    LOGGER.debug(
                        "Fundido cancelado en %s: volumen manual", self.entity_id
                    )
                    return
                expected = start + (target - start) * step / steps
                await self.async_set_volume_level(round(expected, 3))
        except asyncio.CancelledError:
            raise
        finally:
            self._fade_task = None

    @callback
    def _cancel_fade(self) -> None:
        if self._fade_task is not None:
            self._fade_task.cancel()
            self._fade_task = None

    # ------------------------------------------------------------------
    # Servicio google_home_ip.sleep_timer
    # ------------------------------------------------------------------

    async def async_sleep_timer(
        self, *, minutes: float, fade_out: float = DEFAULT_FADE_OUT
    ) -> None:
        """Apaga el altavoz tras ``minutes`` minutos, bajando el volumen antes.

        ``minutes`` a 0 cancela el temporizador en curso.
        """
        self._cancel_sleep_timer()
        if minutes <= 0:
            return
        self._sleep_task = self.hass.async_create_background_task(
            self._async_sleep_timer(minutes * 60, fade_out),
            f"{DOMAIN} sleep {self.entity_id}",
        )

    async def _async_sleep_timer(self, seconds: float, fade_out: float) -> None:
        runtime = self._entry.runtime_data
        runtime.sleep_timer_end = dt_util.utcnow() + timedelta(seconds=seconds)
        async_dispatcher_send(self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id))
        try:
            await asyncio.sleep(max(0.0, seconds - fade_out))
            self._sleep_finishing = True
            if fade_out > 0 and self.available:
                await self._async_fade_to(0.0, fade_out)
            if self.available:
                await self.hass.async_add_executor_job(self._device.turn_off)
            self._fire(EVENT_SLEEP_TIMER_FINISHED)
        except asyncio.CancelledError:
            raise
        finally:
            self._sleep_finishing = False
            self._sleep_task = None
            runtime.sleep_timer_end = None
            async_dispatcher_send(
                self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id)
            )

    @callback
    def _cancel_sleep_timer(self, notify: bool = True) -> None:
        if self._sleep_task is not None:
            self._sleep_task.cancel()
            self._sleep_task = None
        self._entry.runtime_data.sleep_timer_end = None
        if notify:
            async_dispatcher_send(
                self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id)
            )

    async def _async_replay_loop(self, status: Any) -> None:
        """Vuelve a lanzar el audio en bucle cuando termina."""
        url = self._loop_url
        if url is None or not self.available:
            return
        LOGGER.debug("Repitiendo en bucle %s en %s", url, self.entity_id)
        await self.hass.async_add_executor_job(
            lambda: self._device.play_media(
                url,
                status.content_type or guess_mime_type(url),
                status.title,
                stream_type="BUFFERED",
            )
        )

    async def _async_resolve_audio(self, media: str) -> tuple[str, str]:
        """Convierte el parámetro media en una URL accesible y su tipo MIME."""
        media = media.strip()

        if media_source.is_media_source_id(media):
            play_item = await media_source.async_resolve_media(
                self.hass, media, self.entity_id
            )
            url = self._absolute_url(play_item.url)
            return url, play_item.mime_type or guess_mime_type(url)

        if urlparse(media).scheme in ("http", "https"):
            return media, guess_mime_type(media)

        relative = await self.hass.async_add_executor_job(self._local_www_path, media)
        url = f"{self._base_url()}/local/{quote(relative.as_posix())}"
        LOGGER.debug("Ruta local %s convertida a %s", media, url)
        return url, guess_mime_type(url)

    def _base_url(self) -> str:
        """URL de Home Assistant desde la que el altavoz descarga los audios.

        Usa la opción ``base_url`` si está configurada y, si no, la URL interna.
        """
        if configured := self._entry.options.get(CONF_BASE_URL):
            return str(configured)
        try:
            return get_url(self.hass, allow_external=False)
        except NoURLAvailableError:
            LOGGER.warning(
                "No hay URL interna configurada; se usará la URL disponible. "
                "Configúrala en Ajustes > Sistema > Red o en las opciones de la "
                "integración"
            )
        try:
            return get_url(self.hass)
        except NoURLAvailableError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_url"
            ) from err

    def _absolute_url(self, url: str) -> str:
        """Firma las rutas de HA que lo necesitan y las hace absolutas."""
        if url.startswith("/"):
            signed = async_process_play_media_url(
                self.hass, url, allow_relative_url=True
            )
            return f"{self._base_url()}{signed}"
        return async_process_play_media_url(self.hass, url)

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

    async def _async_restore_when_done(self, url: str) -> None:
        """Espera a que termine el audio y restaura el volumen y el audio previo."""
        previous_volume = self._volume_to_restore
        resume = self._media_to_resume

        def playing_ours() -> bool:
            status = self._device.media_status
            return (
                status is not None
                and status.content_id == url
                and self.state in _ACTIVE_STATES
            )

        try:
            async with asyncio.timeout(RESTORE_START_TIMEOUT):
                await self._async_wait_until(playing_ours)
            LOGGER.debug(
                "Audio iniciado en %s; esperando a que termine", self.entity_id
            )
        except TimeoutError:
            LOGGER.debug("El audio no llegó a empezar en %s", self.entity_id)

        try:
            async with asyncio.timeout(RESTORE_MAX_WAIT):
                await self._async_wait_until(
                    lambda: not self.available or not playing_ours()
                )
        except TimeoutError:
            LOGGER.warning("Tiempo máximo de espera agotado en %s", self.entity_id)

        self._volume_to_restore = None
        self._media_to_resume = None
        self._restore_task = None
        if not self.available:
            return

        if previous_volume is not None:
            LOGGER.info(
                "Restaurando volumen de %s a %.2f", self.entity_id, previous_volume
            )
            try:
                await self.async_set_volume_level(previous_volume)
            except HomeAssistantError as err:
                LOGGER.error(
                    "No se pudo restaurar el volumen de %s: %s", self.entity_id, err
                )

        status = self._device.media_status
        if resume is None or (status is not None and status.idle_reason == "CANCELLED"):
            # Sin audio previo, o el usuario detuvo el aviso a mano.
            return
        LOGGER.info("Reanudando %s en %s", resume.url, self.entity_id)
        try:
            await self.hass.async_add_executor_job(
                lambda: self._device.play_media(
                    resume.url,
                    resume.content_type,
                    resume.title,
                    stream_type=resume.stream_type,
                    current_time=resume.position,
                    autoplay=resume.autoplay,
                )
            )
        except HomeAssistantError as err:
            LOGGER.error("No se pudo reanudar el audio en %s: %s", self.entity_id, err)
