"""The Audiobox integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components import mqtt
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .box import BoxController
from .const import SUBENTRY_BOX
from .models import AudioboxConfigEntry, AudioboxRuntime, box_config_from_subentry

PLATFORMS = [Platform.SELECT]


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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AudioboxConfigEntry) -> bool:
    """Stop every box."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        for controller in entry.runtime_data.boxes.values():
            controller.async_stop()
    return unloaded


async def _async_update_listener(
    hass: HomeAssistant, entry: AudioboxConfigEntry
) -> None:
    """Reload only when the entry or a box changed (ADR-32).

    Adding or editing a card must not cancel a box's pending session timer.
    """
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
