"""Integración Google Home IP: reproduce audio en un Google Home por su IP local."""

from __future__ import annotations

import voluptuous as vol

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
    ATTR_MEDIA,
    ATTR_RESTORE_VOLUME,
    ATTR_VOLUME,
    DEFAULT_NAME,
    DOMAIN,
    LOGGER,
    SERVICE_PLAY_AUDIO,
)
from .coordinator import (
    GoogleHomeConfigEntry,
    GoogleHomeData,
    GoogleHomeInfoCoordinator,
)
from .device import GoogleHomeDevice

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLAY_AUDIO_SCHEMA: dict[vol.Marker, object] = {
    vol.Required(ATTR_MEDIA): cv.string,
    vol.Optional(ATTR_VOLUME): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    vol.Optional(ATTR_RESTORE_VOLUME, default=False): cv.boolean,
    vol.Optional(ATTR_ANNOUNCE, default=False): cv.boolean,
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
