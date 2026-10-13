"""Setup, unload, the player select and when boxes reload."""

from types import MappingProxyType

import pytest

from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.audiobox.box import BoxController
from custom_components.audiobox.const import SUBENTRY_BOX

from .common import BOOK_UID, KIDS_ROOM, LED, SELECT, Services, card_subentry, insert


def _box(entry: MockConfigEntry) -> BoxController:
    return next(iter(entry.runtime_data.boxes.values()))


async def test_select_on_the_box_device(
    hass: HomeAssistant, loaded: MockConfigEntry, box_one: dr.DeviceEntry
) -> None:
    state = hass.states.get(SELECT)
    assert state is not None
    assert state.state == "Box"
    assert state.attributes["options"] == ["Box", "Kids room", "Living room"]
    assert er.async_get(hass).async_get(SELECT).device_id == box_one.id


async def test_selecting_an_option(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Kids room"},
        blocking=True,
    )
    assert _box(loaded).selected_player == KIDS_ROOM
    assert hass.states.get(SELECT).state == "Kids room"


@pytest.mark.parametrize(
    ("restored", "expected"), [("Kids room", "Kids room"), ("Garage", "Box")]
)
async def test_selection_restored(
    hass: HomeAssistant,
    mqtt_mock: None,
    entry: MockConfigEntry,
    services: Services,
    restored: str,
    expected: str,
) -> None:
    mock_restore_cache(hass, [State(SELECT, restored)])
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == expected


async def test_adding_a_card_keeps_boxes_running(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    runtime = loaded.runtime_data
    card = card_subentry("04-01-02-03", "library://audiobook/2", "New")
    hass.config_entries.async_add_subentry(
        loaded,
        ConfigSubentry(
            data=MappingProxyType(card["data"]),
            subentry_type=card["subentry_type"],
            title=card["title"],
            unique_id=card["unique_id"],
        ),
    )
    await hass.async_block_till_done()
    assert loaded.runtime_data is runtime


async def test_changing_a_box_reloads(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    runtime = loaded.runtime_data
    box = loaded.get_subentries_of_type(SUBENTRY_BOX)[0]
    hass.config_entries.async_update_subentry(
        loaded, box, data={**box.data, CONF_NAME: "Renamed"}
    )
    await hass.async_block_till_done()
    assert loaded.runtime_data is not runtime
    assert _box(loaded).config.name == "Renamed"


async def test_deleted_entity_is_tolerated(
    hass: HomeAssistant,
    mqtt_mock: None,
    entry: MockConfigEntry,
    services: Services,
    caplog: pytest.LogCaptureFixture,
) -> None:
    er.async_get(hass).async_remove(LED)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert "led_entity entity no longer exists" in caplog.text
    assert _box(entry).config.led_entity is None

    await insert(hass, BOOK_UID)
    assert len(services["music_assistant.play_media"]) == 1
    assert services["light.turn_on"] == []


async def test_unload(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    assert await hass.config_entries.async_unload(loaded.entry_id)
    await hass.async_block_till_done()
    assert loaded.state is ConfigEntryState.NOT_LOADED
