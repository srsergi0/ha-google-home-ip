"""Volumen automático de los avisos según la hora (día y noche)."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import SIGNAL_SETTINGS
from .entity import GoogleHomeEntity
from .models import AnnounceSettings, GoogleHomeConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea los números de volumen día/noche."""
    async_add_entities(
        [
            AnnounceVolumeNumber(
                entry,
                "day_volume",
                lambda s: s.day_volume,
                lambda s, v: setattr(s, "day_volume", v),
            ),
            AnnounceVolumeNumber(
                entry,
                "night_volume",
                lambda s: s.night_volume,
                lambda s, v: setattr(s, "night_volume", v),
            ),
        ]
    )


class AnnounceVolumeNumber(GoogleHomeEntity, RestoreNumber):
    """Porcentaje de volumen de los avisos; lo usa el servicio announce."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.SLIDER
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(
        self,
        entry: GoogleHomeConfigEntry,
        key: str,
        getter: Callable[[AnnounceSettings], float],
        setter: Callable[[AnnounceSettings, float], None],
    ) -> None:
        """Inicializa el número."""
        super().__init__(entry)
        self._entry = entry
        self._getter = getter
        self._setter = setter
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    async def async_added_to_hass(self) -> None:
        """Restaura el último valor guardado."""
        if (last := await self.async_get_last_number_data()) is not None and (
            last.native_value is not None
        ):
            self._setter(self._entry.runtime_data.settings, last.native_value)

    @property
    def native_value(self) -> float:
        """Valor actual."""
        return self._getter(self._entry.runtime_data.settings)

    async def async_set_native_value(self, value: float) -> None:
        """Guarda el nuevo valor."""
        self._setter(self._entry.runtime_data.settings, value)
        self.async_write_ha_state()
        async_dispatcher_send(self.hass, SIGNAL_SETTINGS.format(self._entry.entry_id))
