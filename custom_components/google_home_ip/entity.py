"""Entidad base de Google Home IP."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import GoogleHomeConfigEntry


class GoogleHomeEntity(Entity):
    """Entidad asociada al dispositivo de una entrada."""

    _attr_has_entity_name = True

    def __init__(self, entry: GoogleHomeConfigEntry) -> None:
        """Asocia la entidad al dispositivo creado en async_setup_entry."""
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
