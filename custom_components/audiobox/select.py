"""The selected player of each box."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .box import BoxController
from .models import AudioboxConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AudioboxConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add one player select per box, on the box's own device."""
    device_registry = dr.async_get(hass)
    for subentry_id, controller in entry.runtime_data.boxes.items():
        device = device_registry.async_get(controller.config.device_id)
        async_add_entities(
            [PlayerSelect(controller, device)], config_subentry_id=subentry_id
        )


class PlayerSelect(SelectEntity, RestoreEntity):
    """Which player the box plays on. Survives a restart (ADR-17, ADR-33)."""

    _attr_has_entity_name = True
    _attr_translation_key = "player"
    _attr_should_poll = False

    def __init__(
        self, controller: BoxController, device: dr.DeviceEntry | None
    ) -> None:
        """Attach to the box's device, so it shows up next to its other entities."""
        self._controller = controller
        self._attr_unique_id = f"{controller.config.subentry_id}_player"
        self._attr_options = [player.name for player in controller.config.players]
        # The device belongs to MQTT. Linking through device_entry, as core
        # helpers do, attaches to it; DeviceInfo would create a second device.
        self.device_entry = device

    @property
    def current_option(self) -> str | None:
        """The selected player's name."""
        return self._controller.selected_player_name

    async def async_added_to_hass(self) -> None:
        """Restore the selection, then follow the controller."""
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            self._controller.restore_selection(last.state)
        self.async_on_remove(
            self._controller.async_add_listener(self.async_write_ha_state)
        )

    async def async_select_option(self, option: str) -> None:
        """Select a player by hand."""
        self._controller.select_player_by_name(option)
