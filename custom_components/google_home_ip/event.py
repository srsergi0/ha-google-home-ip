"""Entidad event: expone los avisos del Google Home a las automatizaciones."""

from __future__ import annotations

from typing import Any, Final

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import EVENT_TYPES, SIGNAL_EVENT
from .entity import GoogleHomeEntity
from .models import GoogleHomeConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea la entidad de eventos."""
    async_add_entities([GoogleHomeEventEntity(entry)])


class GoogleHomeEventEntity(GoogleHomeEntity, EventEntity):
    """Dispara un evento por cada aviso, fin de reproducción, error o temporizador.

    Pensada para usarse como disparador de dispositivo en el editor visual de
    automatizaciones.
    """

    _attr_should_poll = False
    _attr_translation_key = "google_home_event"
    _attr_event_types: Final = list(EVENT_TYPES)

    def __init__(self, entry: GoogleHomeConfigEntry) -> None:
        """Inicializa la entidad."""
        super().__init__(entry)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_event"

    async def async_added_to_hass(self) -> None:
        """Se suscribe a los eventos del media_player."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_EVENT.format(self._entry.entry_id),
                self._async_handle_event,
            )
        )

    @callback
    def _async_handle_event(self, event_type: str, data: dict[str, Any]) -> None:
        self._trigger_event(event_type, data)
        self.async_write_ha_state()
