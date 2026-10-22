"""Sensor de conexión Cast de Google Home IP."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GoogleHomeConfigEntry
from .entity import GoogleHomeEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea el sensor de conexión."""
    async_add_entities([GoogleHomeConnectionSensor(entry)])


class GoogleHomeConnectionSensor(GoogleHomeEntity, BinarySensorEntity):
    """Indica si el socket Cast (puerto 8009) está conectado.

    Siempre disponible, para poder automatizar avisos cuando el altavoz se cae.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False
    _attr_translation_key = "cast_connection"

    def __init__(self, entry: GoogleHomeConfigEntry) -> None:
        """Inicializa el sensor."""
        super().__init__(entry)
        self._device = entry.runtime_data.device
        self._attr_unique_id = f"{entry.entry_id}_cast_connection"

    async def async_added_to_hass(self) -> None:
        """Se suscribe a los cambios del dispositivo."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self._device.signal, self.async_write_ha_state
            )
        )

    @property
    def is_on(self) -> bool:
        """Conectado o no."""
        return self._device.connected
