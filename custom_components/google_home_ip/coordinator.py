"""Lectura periódica de la información del dispositivo (API local 8443)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    EUREKA_PARAMS,
    EUREKA_URL,
    INFO_UPDATE_INTERVAL,
    LOGGER,
    REQUEST_TIMEOUT,
)
from .models import GoogleHomeConfigEntry


class GoogleHomeInfoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Lee ``/setup/eureka_info`` del Google Home.

    Devuelve firmware, MAC, modelo, tiempo encendido y estado WiFi. Es la misma
    API que consulta la app Google Home; la lectura no requiere token.
    """

    config_entry: GoogleHomeConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: GoogleHomeConfigEntry, host: str
    ) -> None:
        """Inicializa el coordinador."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {host}",
            update_interval=timedelta(seconds=INFO_UPDATE_INTERVAL),
        )
        self.host = host
        # El dispositivo usa un certificado autofirmado.
        self._session = async_get_clientsession(hass, verify_ssl=False)

    async def _async_update_data(self) -> dict[str, Any]:
        """Descarga eureka_info."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.get(
                    EUREKA_URL.format(host=self.host),
                    params={"params": EUREKA_PARAMS, "options": "detail"},
                )
                response.raise_for_status()
                data = await response.json(content_type=None)
        except (TimeoutError, aiohttp.ClientError, ValueError) as err:
            raise UpdateFailed(f"Sin respuesta de {self.host}:8443 ({err!r})") from err
        if not isinstance(data, dict):
            raise UpdateFailed(f"Respuesta inesperada de {self.host}:8443")
        self._async_update_device_registry(data)
        return data

    @callback
    def _async_update_device_registry(self, data: dict[str, Any]) -> None:
        """Completa la ficha del dispositivo con modelo, firmware y MAC."""
        registry = dr.async_get(self.hass)
        identifier = (DOMAIN, self.config_entry.entry_id)
        # async_get_device está obsoleto en las versiones que tienen la API nueva.
        if hasattr(registry, "async_get_device_by_identifier"):
            device_entry = registry.async_get_device_by_identifier(
                identifier, self.config_entry.entry_id
            )
        else:
            device_entry = registry.async_get_device(identifiers={identifier})
        if device_entry is None:
            return

        device_info: dict[str, Any] = data.get("device_info") or {}
        build_info: dict[str, Any] = data.get("build_info") or {}
        changes: dict[str, Any] = {}
        if (model := device_info.get("model_name")) and model != device_entry.model:
            changes["model"] = model
        if (
            manufacturer := device_info.get("manufacturer")
        ) and manufacturer != device_entry.manufacturer:
            changes["manufacturer"] = manufacturer
        if (
            firmware := build_info.get("cast_build_revision")
        ) and firmware != device_entry.sw_version:
            changes["sw_version"] = firmware
        if mac := device_info.get("mac_address"):
            connection = (dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac))
            if connection not in device_entry.connections:
                changes["new_connections"] = device_entry.connections | {connection}
        if not changes:
            return

        try:
            registry.async_update_device(device_entry.id, **changes)
        except dr.DeviceConnectionCollisionError:
            # Otra integración (p. ej. Google Cast) ya registró esta MAC.
            changes.pop("new_connections")
            if changes:
                registry.async_update_device(device_entry.id, **changes)
