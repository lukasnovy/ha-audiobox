"""Config flow for Audiobox: the entry, boxes and cards."""

from __future__ import annotations

import logging
from typing import Any, override

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import CONF_NOTIFY_ENTITY, DOMAIN
from .models import resolve_entity, to_registry_id

_LOGGER = logging.getLogger(__name__)


def _entry_schema() -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Optional(CONF_NOTIFY_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="notify")
            ),
        }
    )


def _entry_data(hass: HomeAssistant, user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_NOTIFY_ENTITY: to_registry_id(hass, user_input.get(CONF_NOTIFY_ENTITY))
    }


class AudioboxConfigFlow(ConfigFlow, domain=DOMAIN):
    """The Audiobox entry: global settings only."""

    VERSION = 1

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types: boxes and cards."""
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry."""
        if user_input is not None:
            return self.async_create_entry(
                title="Audiobox", data=_entry_data(self.hass, user_input)
            )
        return self.async_show_form(step_id="user", data_schema=_entry_schema())

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the notification target."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            # The update listener reloads the entry because its data changed.
            return self.async_update_and_abort(
                entry, data=_entry_data(self.hass, user_input)
            )
        current = resolve_entity(self.hass, entry.data.get(CONF_NOTIFY_ENTITY))
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _entry_schema(), {CONF_NOTIFY_ENTITY: current} if current else {}
            ),
        )
