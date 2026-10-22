"""Constantes de la integración Google Home IP."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "google_home_ip"

LOGGER: Final = logging.getLogger(__package__)

DEFAULT_NAME: Final = "Google Home"

# Puerto del protocolo Cast (conexión TLS que usa pychromecast).
CAST_PORT: Final = 8009

# Segundos para validar que el dispositivo responde durante la configuración.
CONNECT_TIMEOUT: Final = 5

# Segundos entre reintentos de reconexión del socket Cast.
RETRY_WAIT: Final = 5

# Segundos de espera de cada intento de conexión del socket Cast.
SOCKET_TIMEOUT: Final = 10

# Segundos de espera de las llamadas bloqueantes al dispositivo.
REQUEST_TIMEOUT: Final = 10

SIGNAL_DEVICE_UPDATE: Final = f"{DOMAIN}_device_update_{{}}"

SERVICE_PLAY_AUDIO: Final = "play_audio"
ATTR_MEDIA: Final = "media"
ATTR_VOLUME: Final = "volume"
ATTR_RESTORE_VOLUME: Final = "restore_volume"

# Restauración de volumen tras play_audio.
RESTORE_START_TIMEOUT: Final = 20  # segundos para que empiece la reproducción
RESTORE_MAX_WAIT: Final = 3600  # tope de espera a que termine el audio

DEFAULT_MIME_TYPE: Final = "audio/mpeg"

MIME_TYPES: Final[dict[str, str]] = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
}
