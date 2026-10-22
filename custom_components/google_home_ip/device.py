"""Conexión directa por IP con un Google Home usando pychromecast."""

from __future__ import annotations

from datetime import datetime
import threading
from typing import TYPE_CHECKING
from uuid import UUID

import pychromecast
from pychromecast.controllers.media import MediaStatus, MediaStatusListener
from pychromecast.controllers.receiver import CastStatus, CastStatusListener
from pychromecast.discovery import CastBrowser, SimpleCastListener
from pychromecast.models import CastInfo
from pychromecast.socket_client import (
    CONNECTION_STATUS_CONNECTED,
    ConnectionStatus,
    ConnectionStatusListener,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import dispatcher_send
from homeassistant.util import dt as dt_util

from .const import (
    CAST_PORT,
    DOMAIN,
    LOGGER,
    REQUEST_TIMEOUT,
    RETRY_WAIT,
    SIGNAL_DEVICE_UPDATE,
    SOCKET_TIMEOUT,
)

if TYPE_CHECKING:
    from pychromecast import Chromecast

type GoogleHomeConfigEntry = ConfigEntry[GoogleHomeDevice]


class GoogleHomeDevice(
    ConnectionStatusListener, CastStatusListener, MediaStatusListener
):
    """Mantiene la conexión con un Google Home identificado por su IP.

    pychromecast se usa con ``known_hosts=[ip]`` y sin zeroconf, de modo que no
    se depende del descubrimiento mDNS. El ``HostBrowser`` de pychromecast
    sondea la IP cada 30 s y el socket Cast reintenta la conexión indefinidamente,
    lo que cubre reinicios y cortes del dispositivo.

    Los callbacks de pychromecast llegan desde sus propios hilos; aquí solo se
    guarda el estado y se notifica al bucle de eventos con ``dispatcher_send``.
    """

    def __init__(
        self, hass: HomeAssistant, host: str, name: str, entry_id: str
    ) -> None:
        """Inicializa el dispositivo."""
        self.hass = hass
        self.host = host
        self.name = name
        self.signal = SIGNAL_DEVICE_UPDATE.format(entry_id)

        self._lock = threading.Lock()
        self._browser: CastBrowser | None = None
        self._chromecast: Chromecast | None = None
        self._stopping = False

        self.cast_info: CastInfo | None = None
        self.connected = False
        self.cast_status: CastStatus | None = None
        self.media_status: MediaStatus | None = None
        self.media_status_received: datetime | None = None

    @property
    def uuid(self) -> UUID | None:
        """UUID del dispositivo, si ya se conoce."""
        return self.cast_info.uuid if self.cast_info else None

    @property
    def volume_level(self) -> float | None:
        """Volumen actual (0-1)."""
        return self.cast_status.volume_level if self.cast_status else None

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Arranca el sondeo de la IP en segundo plano."""
        await self.hass.async_add_executor_job(self._start)

    def _start(self) -> None:
        LOGGER.debug("Iniciando conexión directa con %s (%s)", self.name, self.host)
        listener = SimpleCastListener(
            add_callback=self._cast_found,
            remove_callback=self._cast_lost,
            update_callback=self._cast_found,
        )
        # zeroconf_instance=None: solo se usa la IP conocida, sin mDNS.
        self._browser = CastBrowser(listener, None, [self.host])
        self._browser.start_discovery()

    async def async_stop(self) -> None:
        """Cierra la conexión Cast y detiene el browser."""
        await self.hass.async_add_executor_job(self._stop)

    def _stop(self) -> None:
        LOGGER.debug("Cerrando conexión con %s (%s)", self.name, self.host)
        with self._lock:
            self._stopping = True
            browser, self._browser = self._browser, None
            chromecast, self._chromecast = self._chromecast, None
        if browser is not None:
            browser.stop_discovery()
        if chromecast is not None:
            chromecast.disconnect(timeout=REQUEST_TIMEOUT)
        self.connected = False

    # ------------------------------------------------------------------
    # Callbacks del HostBrowser (hilo de pychromecast)
    # ------------------------------------------------------------------

    def _cast_found(self, uuid: UUID, _service: str) -> None:
        """El HostBrowser ha encontrado (o actualizado) un dispositivo en la IP."""
        if self._browser is None:
            return
        cast_info = self._browser.devices.get(uuid)
        # Un altavoz con grupos multizona también anuncia los grupos; solo nos
        # interesa el propio dispositivo en el puerto Cast estándar.
        if (
            cast_info is None
            or cast_info.host != self.host
            or cast_info.port != CAST_PORT
        ):
            return

        with self._lock:
            if self._stopping:
                return
            previous = self._chromecast
            if previous is not None and previous.uuid == uuid:
                # Mismo dispositivo: el socket ya se encarga de reconectar.
                self.cast_info = cast_info
                return

            LOGGER.info(
                "Google Home encontrado en %s: %s (%s, uuid %s)",
                self.host,
                cast_info.friendly_name,
                cast_info.model_name,
                uuid,
            )
            chromecast = pychromecast.get_chromecast_from_cast_info(
                cast_info,
                zconf=None,
                tries=None,  # reintentos indefinidos
                retry_wait=RETRY_WAIT,
                timeout=SOCKET_TIMEOUT,
            )
            chromecast.register_connection_listener(self)
            chromecast.register_status_listener(self)
            chromecast.media_controller.register_status_listener(self)
            self._chromecast = chromecast
            self.cast_info = cast_info
            self.cast_status = None
            self.media_status = None

        if previous is not None:
            LOGGER.info(
                "Otro dispositivo responde ahora en %s; reconectando", self.host
            )
            previous.disconnect(timeout=REQUEST_TIMEOUT)
        chromecast.start()
        self._notify()

    def _cast_lost(self, uuid: UUID, _service: str, _cast_info: CastInfo) -> None:
        """El HostBrowser ha dejado de recibir respuesta de la IP."""
        LOGGER.debug("%s (%s) no responde al sondeo HTTP", self.name, self.host)

    # ------------------------------------------------------------------
    # Listeners de pychromecast (hilo del socket)
    # ------------------------------------------------------------------

    def new_connection_status(self, status: ConnectionStatus) -> None:
        """Cambio en el estado de la conexión Cast."""
        connected = status.status == CONNECTION_STATUS_CONNECTED
        if connected != self.connected:
            if connected:
                LOGGER.info("Conectado con %s (%s)", self.name, self.host)
            else:
                LOGGER.warning(
                    "Conexión perdida con %s (%s): %s. Reintentando cada %s s",
                    self.name,
                    self.host,
                    status.status,
                    RETRY_WAIT,
                )
        else:
            LOGGER.debug("Estado de conexión de %s: %s", self.host, status.status)
        self.connected = connected
        if not connected:
            self.media_status = None
        self._notify()

    def new_cast_status(self, status: CastStatus) -> None:
        """Cambio en el estado general (app activa, volumen...)."""
        LOGGER.debug("Estado Cast de %s: %s", self.host, status)
        self.cast_status = status
        self._notify()

    def new_media_status(self, status: MediaStatus) -> None:
        """Cambio en el estado del reproductor."""
        LOGGER.debug(
            "Estado multimedia de %s: %s (%s)",
            self.host,
            status.player_state,
            status.content_id,
        )
        if status.idle_reason == "ERROR":
            LOGGER.error(
                "%s no pudo reproducir %s. Comprueba que la URL es accesible desde "
                "el Google Home y que el formato es compatible",
                self.name,
                status.content_id,
            )
        self.media_status = status
        self.media_status_received = dt_util.utcnow()
        self._notify()

    def load_media_failed(self, queue_item_id: int, error_code: int) -> None:
        """El Google Home no ha podido cargar el audio."""
        LOGGER.error(
            "%s no pudo cargar el audio (item %s, código %s). Comprueba que la URL "
            "es accesible desde el Google Home y que el formato es compatible",
            self.name,
            queue_item_id,
            error_code,
        )

    def _notify(self) -> None:
        dispatcher_send(self.hass, self.signal)

    # ------------------------------------------------------------------
    # Comandos (bloqueantes: llamarlos con async_add_executor_job)
    # ------------------------------------------------------------------

    def _require_chromecast(self) -> Chromecast:
        chromecast = self._chromecast
        if chromecast is None or not self.connected:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_connected",
                translation_placeholders={"name": self.name, "host": self.host},
            )
        return chromecast

    def play_media(self, url: str, content_type: str, title: str | None) -> None:
        """Envía un audio al Default Media Receiver."""
        chromecast = self._require_chromecast()
        LOGGER.info("Reproduciendo en %s: %s (%s)", self.name, url, content_type)
        chromecast.media_controller.play_media(
            url,
            content_type,
            title=title,
            stream_type="BUFFERED",
        )

    def play(self) -> None:
        """Reanuda la reproducción."""
        self._require_chromecast().media_controller.play(timeout=REQUEST_TIMEOUT)

    def pause(self) -> None:
        """Pausa la reproducción."""
        self._require_chromecast().media_controller.pause(timeout=REQUEST_TIMEOUT)

    def stop(self) -> None:
        """Detiene la reproducción."""
        self._require_chromecast().media_controller.stop(timeout=REQUEST_TIMEOUT)

    def set_volume(self, volume: float) -> None:
        """Fija el volumen (0-1)."""
        self._require_chromecast().set_volume(volume, timeout=REQUEST_TIMEOUT)

    def volume_up(self, delta: float) -> None:
        """Sube el volumen."""
        self._require_chromecast().volume_up(delta, timeout=REQUEST_TIMEOUT)

    def volume_down(self, delta: float) -> None:
        """Baja el volumen."""
        self._require_chromecast().volume_down(delta, timeout=REQUEST_TIMEOUT)

    def set_muted(self, muted: bool) -> None:
        """Silencia o reactiva el sonido."""
        self._require_chromecast().set_volume_muted(muted, timeout=REQUEST_TIMEOUT)
