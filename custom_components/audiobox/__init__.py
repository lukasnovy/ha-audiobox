"""The Audiobox integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components import mqtt
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .box import BoxController
from .const import DOMAIN, SIGNAL_PANEL_UPDATE, SUBENTRY_BOX
from .models import (
    DATA_AUDIOBOX,
    AudioboxConfigEntry,
    AudioboxData,
    AudioboxRuntime,
    box_config_from_subentry,
)
from .panel import async_register_panel, async_remove_panel, async_setup_panel_api

PLATFORMS = [Platform.SELECT]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Keep what the pairing panel needs across entry reloads."""
    hass.data.setdefault(DATA_AUDIOBOX, AudioboxData())
    await async_setup_panel_api(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: AudioboxConfigEntry) -> bool:
    """Set up one controller per box."""
    if not await mqtt.async_wait_for_mqtt_client(hass):
        raise ConfigEntryNotReady("MQTT is not available")

    runtime = AudioboxRuntime(snapshot=_snapshot(entry))
    for subentry in entry.get_subentries_of_type(SUBENTRY_BOX):
        runtime.boxes[subentry.subentry_id] = BoxController(
            hass, entry, box_config_from_subentry(hass, subentry)
        )
    entry.runtime_data = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    for controller in runtime.boxes.values():
        await controller.async_start()
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await async_register_panel(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AudioboxConfigEntry) -> bool:
    """Stop every box."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        for controller in entry.runtime_data.boxes.values():
            controller.async_stop()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: AudioboxConfigEntry) -> None:
    """Take the panel out of the sidebar."""
    async_remove_panel(hass)


async def _async_update_listener(
    hass: HomeAssistant, entry: AudioboxConfigEntry
) -> None:
    """Reload only when the entry or a box changed (ADR-32).

    Adding or editing a card must not cancel a box's pending session timer.
    """
    async_dispatcher_send(hass, SIGNAL_PANEL_UPDATE)
    if _snapshot(entry) != entry.runtime_data.snapshot:
        await hass.config_entries.async_reload(entry.entry_id)


def _snapshot(entry: AudioboxConfigEntry) -> dict[str, Any]:
    return {
        "data": dict(entry.data),
        "boxes": {
            subentry.subentry_id: dict(subentry.data)
            for subentry in entry.get_subentries_of_type(SUBENTRY_BOX)
        },
    }
