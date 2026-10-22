"""Integración Google Home IP: reproduce audio en un Google Home por su IP local."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.media_player import DOMAIN as MEDIA_PLAYER_DOMAIN
from homeassistant.const import CONF_HOST, CONF_NAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_MEDIA,
    ATTR_RESTORE_VOLUME,
    ATTR_VOLUME,
    DOMAIN,
    LOGGER,
    SERVICE_PLAY_AUDIO,
)
from .device import GoogleHomeConfigEntry, GoogleHomeDevice

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLAY_AUDIO_SCHEMA: dict[vol.Marker, object] = {
    vol.Required(ATTR_MEDIA): cv.string,
    vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    vol.Optional(ATTR_RESTORE_VOLUME, default=False): cv.boolean,
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra el servicio google_home_ip.play_audio."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_PLAY_AUDIO,
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema=PLAY_AUDIO_SCHEMA,
        func="async_play_audio",
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> bool:
    """Configura un Google Home a partir de una entrada."""
    device = GoogleHomeDevice(
        hass, entry.data[CONF_HOST], entry.data[CONF_NAME], entry.entry_id
    )
    # No se espera a que el dispositivo responda: si está apagado, la entidad
    # aparece como no disponible y se conecta sola cuando vuelva.
    await device.async_start()
    entry.runtime_data = device

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    LOGGER.debug("Entrada %s configurada para %s", entry.title, device.host)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GoogleHomeConfigEntry) -> bool:
    """Descarga la entrada y cierra la conexión con el dispositivo."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok
