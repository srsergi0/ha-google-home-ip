"""Sensores de diagnóstico de Google Home IP (API local 8443)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import GoogleHomeConfigEntry, GoogleHomeInfoCoordinator
from .entity import GoogleHomeEntity

PARALLEL_UPDATES = 0

# Diferencia mínima para considerar que el dispositivo se ha reiniciado; evita
# que el valor oscile por el redondeo del uptime y la latencia de la petición.
BOOT_TIME_TOLERANCE = timedelta(minutes=2)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GoogleHomeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea los sensores de diagnóstico."""
    async_add_entities(
        [GoogleHomeWifiSignalSensor(entry), GoogleHomeLastBootSensor(entry)]
    )


class GoogleHomeInfoSensor(
    GoogleHomeEntity, CoordinatorEntity[GoogleHomeInfoCoordinator], SensorEntity
):
    """Sensor basado en eureka_info."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: GoogleHomeConfigEntry, key: str) -> None:
        """Inicializa el sensor."""
        GoogleHomeEntity.__init__(self, entry)
        CoordinatorEntity.__init__(self, entry.runtime_data.coordinator)
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    def _section(self, name: str) -> dict[str, Any]:
        return (self.coordinator.data or {}).get(name) or {}


class GoogleHomeWifiSignalSensor(GoogleHomeInfoSensor):
    """Intensidad de la señal WiFi que recibe el altavoz."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: GoogleHomeConfigEntry) -> None:
        """Inicializa el sensor."""
        super().__init__(entry, "wifi_signal")

    @property
    def available(self) -> bool:
        """Disponible si el dispositivo informa de la señal."""
        return super().available and self.native_value is not None

    @property
    def native_value(self) -> int | None:
        """Señal en dBm."""
        return self._section("wifi").get("signal_level")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Red, punto de acceso y ruido."""
        wifi = self._section("wifi")
        return {
            "ssid": wifi.get("ssid"),
            "bssid": wifi.get("bssid"),
            "noise_level": wifi.get("noise_level"),
            "ip_address": self._section("net").get("ip_address"),
        }


class GoogleHomeLastBootSensor(GoogleHomeInfoSensor):
    """Momento del último arranque del altavoz."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: GoogleHomeConfigEntry) -> None:
        """Inicializa el sensor."""
        super().__init__(entry, "last_boot")
        self._boot_time: datetime | None = None

    def _update_boot_time(self) -> None:
        uptime = self._section("device_info").get("uptime")
        if not isinstance(uptime, int | float):
            return
        boot_time = (dt_util.utcnow() - timedelta(seconds=uptime)).replace(
            microsecond=0
        )
        if self._boot_time is None or abs(boot_time - self._boot_time) > (
            BOOT_TIME_TOLERANCE
        ):
            self._boot_time = boot_time

    def _handle_coordinator_update(self) -> None:
        self._update_boot_time()
        super()._handle_coordinator_update()

    async def async_added_to_hass(self) -> None:
        """Calcula el valor inicial con los datos ya descargados."""
        await super().async_added_to_hass()
        self._update_boot_time()

    @property
    def native_value(self) -> datetime | None:
        """Hora del último arranque."""
        return self._boot_time
