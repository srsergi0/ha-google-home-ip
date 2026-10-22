"""Integración Google Home IP: reproduce audio en un Google Home por su IP local."""

from __future__ import annotations

from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import CONF_HOST, CONF_NAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    service,
)
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_ANNOUNCE,
    ATTR_CHIME,
    ATTR_DURATION,
    ATTR_FADE_IN,
    ATTR_FADE_OUT,
    ATTR_LANGUAGE,
    ATTR_LOOP,
    ATTR_MEDIA,
    ATTR_MESSAGE,
    ATTR_MINUTES,
    ATTR_RESTORE_VOLUME,
    ATTR_RESUME,
    ATTR_TTS_ENTITY,
    ATTR_VOLUME,
    CHIMES,
    CHIMES_URL,
    DEFAULT_FADE_OUT,
    DEFAULT_NAME,
    DOMAIN,
    LOGGER,
    SERVICE_ANNOUNCE,
    SERVICE_FADE_VOLUME,
    SERVICE_PLAY_AUDIO,
    SERVICE_SLEEP_TIMER,
)
from .coordinator import GoogleHomeInfoCoordinator
from .device import GoogleHomeDevice
from .models import GoogleHomeConfigEntry, GoogleHomeData

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.EVENT,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.TIME,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_VOLUME = vol.All(vol.Coerce(float), vol.Range(min=0, max=1))

PLAY_AUDIO_SCHEMA: dict[vol.Marker, object] = {
    vol.Required(ATTR_MEDIA): cv.string,
    vol.Optional(ATTR_VOLUME): _VOLUME,
    vol.Optional(ATTR_RESTORE_VOLUME, default=False): cv.boolean,
    vol.Optional(ATTR_ANNOUNCE, default=False): cv.boolean,
    vol.Optional(ATTR_LOOP, default=False): cv.boolean,
    vol.Optional(ATTR_FADE_IN): vol.All(vol.Coerce(float), vol.Range(min=0)),
}

ANNOUNCE_SCHEMA: dict[vol.Marker, object] = {
    vol.Optional(ATTR_MESSAGE): cv.string,
    vol.Optional(ATTR_MEDIA): cv.string,
    vol.Optional(ATTR_CHIME): cv.string,
    vol.Optional(ATTR_VOLUME): _VOLUME,
    vol.Optional(ATTR_TTS_ENTITY): cv.entity_id,
    vol.Optional(ATTR_LANGUAGE): cv.string,
    vol.Optional(ATTR_RESUME, default=True): cv.boolean,
    vol.Optional(ATTR_FADE_IN): vol.All(vol.Coerce(float), vol.Range(min=0)),
}

FADE_VOLUME_SCHEMA: dict[vol.Marker, object] = {
    vol.Required(ATTR_VOLUME): _VOLUME,
    vol.Required(ATTR_DURATION): vol.All(vol.Coerce(float), vol.Range(min=0)),
}

SLEEP_TIMER_SCHEMA: dict[vol.Marker, object] = {
    vol.Required(ATTR_MINUTES): vol.All(vol.Coerce(float), vol.Range(min=0)),
    vol.Optional(ATTR_FADE_OUT, default=DEFAULT_FADE_OUT): vol.All(
        vol.Coerce(float), vol.Range(min=0)
    ),
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra los servicios y sirve las campanitas."""
    chimes_dir = Path(__file__).parent / "chimes"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CHIMES_URL, str(chimes_dir), cache_headers=True)]
    )

    for name, schema, func in (
        (SERVICE_PLAY_AUDIO, PLAY_AUDIO_SCHEMA, "async_play_audio"),
        (SERVICE_ANNOUNCE, ANNOUNCE_SCHEMA, "async_announce"),
        (SERVICE_FADE_VOLUME, FADE_VOLUME_SCHEMA, "async_fade_volume"),
        (SERVICE_SLEEP_TIMER, SLEEP_TIMER_SCHEMA, "async_sleep_timer"),
    ):
        service.async_register_platform_entity_service(
            hass,
            DOMAIN,
            name,
            entity_domain=MEDIA_PLAYER_DOMAIN,
            schema=schema,
            func=func,
        )
    LOGGER.debug("Campanitas disponibles: %s", ", ".join(CHIMES))
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> bool:
    """Configura un Google Home a partir de una entrada."""
    host: str = entry.data[CONF_HOST]
    device = GoogleHomeDevice(hass, host, entry.data[CONF_NAME], entry.entry_id)
    coordinator = GoogleHomeInfoCoordinator(hass, entry, host)
    entry.runtime_data = GoogleHomeData(device=device, coordinator=coordinator)

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=device.name,
        manufacturer="Google",
        model=DEFAULT_NAME,
    )

    # No se espera a que el dispositivo responda: si está apagado, las entidades
    # aparecen como no disponibles y se conectan solas cuando vuelva.
    await device.async_start()
    await coordinator.async_refresh()

    @callback
    def _async_device_updated() -> None:
        # Al reconectar el socket Cast, actualiza la información sin esperar
        # al siguiente sondeo.
        if device.connected and not coordinator.last_update_success:
            hass.async_create_task(coordinator.async_request_refresh())

    entry.async_on_unload(
        async_dispatcher_connect(hass, device.signal, _async_device_updated)
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.debug("Entrada %s configurada para %s", entry.title, host)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> bool:
    """Descarga la entrada y cierra la conexión con el dispositivo."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.device.async_stop()
    return unload_ok
