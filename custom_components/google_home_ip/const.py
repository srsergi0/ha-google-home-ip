"""Constantes de la integración Google Home IP."""

from __future__ import annotations

import logging
from typing import Final

DOMAIN: Final = "google_home_ip"

LOGGER: Final = logging.getLogger(__package__)

DEFAULT_NAME: Final = "Google Home"

# Opción: URL de Home Assistant que usa el altavoz para descargar audios
# locales y TTS (por ejemplo, la URL pública si HA está en otra red).
CONF_BASE_URL: Final = "base_url"

# Puerto del protocolo Cast (conexión TLS que usa pychromecast).
CAST_PORT: Final = 8009

# API local de configuración (HTTPS con certificado autofirmado). La lectura de
# eureka_info no necesita token.
EUREKA_URL: Final = "https://{host}:8443/setup/eureka_info"
EUREKA_PARAMS: Final = "name,build_info,device_info,net,wifi"

# Segundos entre lecturas de eureka_info (señal WiFi, firmware, uptime).
INFO_UPDATE_INTERVAL: Final = 60

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
ATTR_ANNOUNCE: Final = "announce"

# Restauración de volumen y del audio interrumpido tras un aviso.
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

# Opciones: motor TTS e idioma por defecto para google_home_ip.announce.
CONF_TTS_ENTITY: Final = "tts_entity"
CONF_LANGUAGE: Final = "language"

# Campanitas servidas por Home Assistant (sin autenticación, como /local).
CHIMES_URL: Final = f"/{DOMAIN}/chimes"
CHIMES: Final = ("ding", "ding_dong", "aviso", "alerta")
CHIME_NONE: Final = "none"
DEFAULT_CHIME: Final = "ding"

SIGNAL_EVENT: Final = f"{DOMAIN}_event_{{}}"
# Evento de bus para los disparadores de dispositivo (editor visual).
DEVICE_EVENT: Final = f"{DOMAIN}_event"
SIGNAL_SETTINGS: Final = f"{DOMAIN}_settings_{{}}"

SERVICE_ANNOUNCE: Final = "announce"
SERVICE_FADE_VOLUME: Final = "fade_volume"
SERVICE_SLEEP_TIMER: Final = "sleep_timer"
ATTR_MESSAGE: Final = "message"
ATTR_CHIME: Final = "chime"
ATTR_TTS_ENTITY: Final = "tts_entity"
ATTR_LANGUAGE: Final = "language"
ATTR_RESUME: Final = "resume"
ATTR_FADE_IN: Final = "fade_in"
ATTR_DURATION: Final = "duration"
ATTR_LOOP: Final = "loop"
ATTR_MINUTES: Final = "minutes"
ATTR_FADE_OUT: Final = "fade_out"

# Tipos de la entidad event.
EVENT_ANNOUNCEMENT_STARTED: Final = "announcement_started"
EVENT_ANNOUNCEMENT_FINISHED: Final = "announcement_finished"
EVENT_PLAYBACK_FINISHED: Final = "playback_finished"
EVENT_PLAYBACK_ERROR: Final = "playback_error"
EVENT_SLEEP_TIMER_FINISHED: Final = "sleep_timer_finished"
EVENT_TYPES: Final = (
    EVENT_ANNOUNCEMENT_STARTED,
    EVENT_ANNOUNCEMENT_FINISHED,
    EVENT_PLAYBACK_FINISHED,
    EVENT_PLAYBACK_ERROR,
    EVENT_SLEEP_TIMER_FINISHED,
)

# Volumen automático de los avisos (en %), y horario nocturno por defecto.
DEFAULT_DAY_VOLUME: Final = 50
DEFAULT_NIGHT_VOLUME: Final = 20
DEFAULT_NIGHT_START: Final = "22:00"
DEFAULT_NIGHT_END: Final = "07:00"

# Fundidos de volumen.
FADE_MIN_INTERVAL: Final = 0.5  # segundos mínimos entre pasos
FADE_MAX_STEPS: Final = 120
FADE_ABORT_DELTA: Final = 0.03  # si alguien cambia el volumen a mano, se para
DEFAULT_FADE_OUT: Final = 30  # segundos de bajada al terminar el temporizador
