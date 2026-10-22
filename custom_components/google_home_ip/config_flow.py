"""Config flow de Google Home IP."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import ipaddress
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import callback

from .const import (
    CAST_PORT,
    CONF_BASE_URL,
    CONNECT_TIMEOUT,
    DEFAULT_NAME,
    DOMAIN,
    LOGGER,
)


def _normalize_host(host: str) -> str | None:
    """Devuelve la IP normalizada o None si no es una IP válida."""
    try:
        return str(ipaddress.ip_address(host.strip()))
    except ValueError:
        return None


def _normalize_base_url(url: str) -> str | None:
    """Devuelve la URL sin barra final, "" si está vacía o None si no es válida."""
    url = url.strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.path or parsed.query or parsed.fragment:
        return None
    return url


async def async_can_connect(host: str) -> bool:
    """Comprueba que el dispositivo acepta conexiones en el puerto Cast (8009)."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            _reader, writer = await asyncio.open_connection(host, CAST_PORT)
    except (TimeoutError, OSError) as err:
        LOGGER.debug("Sin respuesta de %s:%s: %r", host, CAST_PORT, err)
        return False
    writer.close()
    with suppress(OSError):
        await writer.wait_closed()
    return True


class GoogleHomeIpConfigFlow(ConfigFlow, domain=DOMAIN):
    """Añade un Google Home por IP."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pide la IP y el nombre del dispositivo."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = _normalize_host(user_input[CONF_HOST])
            name = user_input[CONF_NAME].strip() or DEFAULT_NAME
            if host is None:
                errors[CONF_HOST] = "invalid_host"
            else:
                self._async_abort_entries_match({CONF_HOST: host})
                if await async_can_connect(host):
                    LOGGER.info("Añadiendo Google Home %s en %s", name, host)
                    return self.async_create_entry(
                        title=name, data={CONF_HOST: host, CONF_NAME: name}
                    )
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_HOST): str,
                        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Devuelve el options flow."""
        return GoogleHomeIpOptionsFlow()


class GoogleHomeIpOptionsFlow(OptionsFlow):
    """Permite cambiar la IP y la URL de Home Assistant de un Google Home."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pide la IP y, opcionalmente, la URL base para los audios."""
        errors: dict[str, str] = {}
        entry = self.config_entry
        current_host: str = entry.data[CONF_HOST]

        if user_input is not None:
            host = _normalize_host(user_input[CONF_HOST])
            base_url = _normalize_base_url(user_input.get(CONF_BASE_URL, ""))
            if host is None:
                errors[CONF_HOST] = "invalid_host"
            elif base_url is None:
                errors[CONF_BASE_URL] = "invalid_url"
            elif host != current_host and any(
                other.data.get(CONF_HOST) == host
                for other in self.hass.config_entries.async_entries(DOMAIN)
                if other.entry_id != entry.entry_id
            ):
                errors[CONF_HOST] = "already_configured"
            elif not await async_can_connect(host):
                errors["base"] = "cannot_connect"
            else:
                if host != current_host:
                    LOGGER.info(
                        "Cambiando la IP de %s: %s -> %s",
                        entry.title,
                        current_host,
                        host,
                    )
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_HOST: host}
                    )
                    self.hass.config_entries.async_schedule_reload(entry.entry_id)
                options = {**entry.options, CONF_BASE_URL: base_url}
                if not base_url:
                    options.pop(CONF_BASE_URL)
                return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_HOST): str,
                        vol.Optional(CONF_BASE_URL): str,
                    }
                ),
                user_input
                or {
                    CONF_HOST: current_host,
                    CONF_BASE_URL: entry.options.get(CONF_BASE_URL, ""),
                },
            ),
            errors=errors,
            description_placeholders={
                "name": entry.title,
                "example_url": "https://ha.example.com",
            },
        )
