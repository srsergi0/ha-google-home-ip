"""Diagnóstico descargable de Google Home IP."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_BASE_URL
from .coordinator import GoogleHomeConfigEntry

TO_REDACT = {
    CONF_BASE_URL,
    "bssid",
    "cloud_device_id",
    "hotspot_bssid",
    "local_authorization_token_hash",
    "mac_address",
    "public_key",
    "ssdp_udn",
    "ssid",
    "uma_client_id",
    "uuid",
}


def _as_dict(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GoogleHomeConfigEntry
) -> dict[str, Any]:
    """Estado de la conexión Cast y datos de eureka_info."""
    device = entry.runtime_data.device
    coordinator = entry.runtime_data.coordinator
    media_status = device.media_status
    cast_info = device.cast_info
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "connected": device.connected,
            "cast_info": (
                {
                    "uuid": str(cast_info.uuid),
                    "model_name": cast_info.model_name,
                    "manufacturer": cast_info.manufacturer,
                    "cast_type": cast_info.cast_type,
                }
                if cast_info
                else None
            ),
            "cast_status": _as_dict(device.cast_status),
            "media_status": (
                {
                    key: getattr(media_status, key)
                    for key in (
                        "player_state",
                        "idle_reason",
                        "content_id",
                        "content_type",
                        "stream_type",
                        "duration",
                        "current_time",
                        "title",
                        "supported_media_commands",
                    )
                }
                if media_status
                else None
            ),
            "eureka_info": {
                "last_update_success": coordinator.last_update_success,
                "data": coordinator.data,
            },
        },
        TO_REDACT,
    )
