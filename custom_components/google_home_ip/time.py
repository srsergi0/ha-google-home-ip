"""Horario nocturno para el volumen automático de los avisos."""

from __future__ import annotations

from collections.abc import Callable
import contextlib
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import GoogleHomeEntity
from .models import AnnounceSettings, GoogleHomeConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea las horas de inicio y fin del tramo nocturno."""
    async_add_entities(
        [
            NightTime(
                entry,
                "night_start",
                lambda s: s.night_start,
                lambda s, v: setattr(s, "night_start", v),
            ),
            NightTime(
                entry,
                "night_end",
                lambda s: s.night_end,
                lambda s, v: setattr(s, "night_end", v),
            ),
        ]
    )


class NightTime(GoogleHomeEntity, TimeEntity, RestoreEntity):
    """Hora de inicio o fin del tramo nocturno de los avisos."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: GoogleHomeConfigEntry,
        key: str,
        getter: Callable[[AnnounceSettings], time],
        setter: Callable[[AnnounceSettings, time], None],
    ) -> None:
        """Inicializa la hora."""
        super().__init__(entry)
        self._entry = entry
        self._getter = getter
        self._setter = setter
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    async def async_added_to_hass(self) -> None:
        """Restaura el último valor guardado."""
        if (last := await self.async_get_last_state()) is not None:
            with contextlib.suppress(ValueError):
                self._setter(
                    self._entry.runtime_data.settings, time.fromisoformat(last.state)
                )

    @property
    def native_value(self) -> time:
        """Valor actual."""
        return self._getter(self._entry.runtime_data.settings)

    async def async_set_value(self, value: time) -> None:
        """Guarda la nueva hora."""
        self._setter(self._entry.runtime_data.settings, value)
        self.async_write_ha_state()
