"""Datos de ejecución compartidos por las entidades de una entrada."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_DAY_VOLUME,
    DEFAULT_NIGHT_END,
    DEFAULT_NIGHT_START,
    DEFAULT_NIGHT_VOLUME,
)

if TYPE_CHECKING:
    from .coordinator import GoogleHomeInfoCoordinator
    from .device import GoogleHomeDevice


@dataclass
class AnnounceSettings:
    """Volumen automático de los avisos según la hora.

    Los valores los mantienen las entidades number y time, que los restauran
    tras un reinicio.
    """

    day_volume: float = DEFAULT_DAY_VOLUME
    night_volume: float = DEFAULT_NIGHT_VOLUME
    night_start: time = field(
        default_factory=lambda: time.fromisoformat(DEFAULT_NIGHT_START)
    )
    night_end: time = field(
        default_factory=lambda: time.fromisoformat(DEFAULT_NIGHT_END)
    )

    def is_night(self, now: datetime | None = None) -> bool:
        """Indica si ahora es de noche (el tramo puede cruzar la medianoche)."""
        current = (now or dt_util.now()).time()
        start, end = self.night_start, self.night_end
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end

    def announce_volume(self, now: datetime | None = None) -> float:
        """Volumen (0-1) que toca para un aviso ahora."""
        percent = self.night_volume if self.is_night(now) else self.day_volume
        return max(0.0, min(1.0, percent / 100))


@dataclass
class GoogleHomeData:
    """Datos de ejecución de una entrada."""

    device: GoogleHomeDevice
    coordinator: GoogleHomeInfoCoordinator
    settings: AnnounceSettings = field(default_factory=AnnounceSettings)
    sleep_timer_end: datetime | None = None


type GoogleHomeConfigEntry = ConfigEntry[GoogleHomeData]
