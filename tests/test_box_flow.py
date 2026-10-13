"""Tests for the box form."""

from typing import Any

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiobox.const import (
    CONF_BATTERY_ENTITY,
    CONF_CARD_ENTITY,
    CONF_CARD_PRESENT_ENTITY,
    CONF_DEVICE_ID,
    CONF_LED_ENTITY,
    CONF_MA_USER,
    CONF_MQTT_PREFIX,
    CONF_NOTIFY_ENTITY,
    CONF_PLAYERS,
    CONF_VOLUME_ENTITY,
    DOMAIN,
    SUBENTRY_BOX,
)

from .common import BOX_PLAYER, KIDS_ROOM, PLAYERS_ONE, box_subentry, suggested

pytestmark = pytest.mark.usefixtures("mqtt_mock", "players")


def _player(entity: str, name: str, colour: str = "white") -> dict[str, str]:
    return {"entity": entity, "name": name, "colour": colour}


DETAILS: dict[str, Any] = {
    CONF_NAME: "Kids box",
    CONF_MQTT_PREFIX: "audiobox1",
    CONF_MA_USER: "child1",
    CONF_CARD_ENTITY: "sensor.audiobox_1_card",
    CONF_CARD_PRESENT_ENTITY: "binary_sensor.audiobox_1_card_present",
    CONF_VOLUME_ENTITY: "number.audiobox_1_volume",
    CONF_BATTERY_ENTITY: "sensor.audiobox_1_battery",
    CONF_LED_ENTITY: "light.audiobox_1_led",
    CONF_PLAYERS: [_player(BOX_PLAYER, "Box"), _player(KIDS_ROOM, "Kids room", "blue")],
}


@pytest.fixture
def plain_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_NOTIFY_ENTITY: None})
    entry.add_to_hass(hass)
    return entry


async def _start(hass: HomeAssistant, entry: MockConfigEntry) -> Any:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_BOX), context={"source": SOURCE_USER}
    )


async def _submit(hass: HomeAssistant, result: Any, user_input: dict[str, Any]) -> Any:
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


async def test_details_are_guessed_from_the_device(
    hass: HomeAssistant, plain_entry: MockConfigEntry, box_one: dr.DeviceEntry
) -> None:
    result = await _start(hass, plain_entry)
    assert result["step_id"] == "device"
    result = await _submit(hass, result, {CONF_DEVICE_ID: box_one.id})
    assert result["step_id"] == "details"

    assert suggested(result, CONF_NAME) == "Audiobox 1"
    assert suggested(result, CONF_MQTT_PREFIX) == "audiobox1"
    assert suggested(result, CONF_CARD_ENTITY) == "sensor.audiobox_1_card"
    assert (
        suggested(result, CONF_CARD_PRESENT_ENTITY)
        == "binary_sensor.audiobox_1_card_present"
    )
    assert suggested(result, CONF_VOLUME_ENTITY) == "number.audiobox_1_volume"
    assert suggested(result, CONF_BATTERY_ENTITY) == "sensor.audiobox_1_battery"
    assert suggested(result, CONF_LED_ENTITY) == "light.audiobox_1_led"
    assert suggested(result, CONF_MA_USER) is None
    assert suggested(result, CONF_PLAYERS) == [_player(BOX_PLAYER, "Audiobox 1")]


async def test_box_is_stored_with_registry_ids(
    hass: HomeAssistant, plain_entry: MockConfigEntry, box_one: dr.DeviceEntry
) -> None:
    ent_reg = er.async_get(hass)
    result = await _start(hass, plain_entry)
    result = await _submit(hass, result, {CONF_DEVICE_ID: box_one.id})
    result = await _submit(hass, result, DETAILS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Kids box"

    subentry = next(iter(plain_entry.subentries.values()))
    assert subentry.unique_id == box_one.id
    data = subentry.data
    assert data[CONF_DEVICE_ID] == box_one.id
    assert data[CONF_CARD_ENTITY] == ent_reg.async_get("sensor.audiobox_1_card").id
    assert data[CONF_LED_ENTITY] == ent_reg.async_get("light.audiobox_1_led").id
    assert data[CONF_PLAYERS] == [
        _player(ent_reg.async_get(BOX_PLAYER).id, "Box"),
        _player(ent_reg.async_get(KIDS_ROOM).id, "Kids room", "blue"),
    ]


async def test_battery_is_optional(
    hass: HomeAssistant, plain_entry: MockConfigEntry, box_one: dr.DeviceEntry
) -> None:
    result = await _start(hass, plain_entry)
    result = await _submit(hass, result, {CONF_DEVICE_ID: box_one.id})
    details = {k: v for k, v in DETAILS.items() if k != CONF_BATTERY_ENTITY}
    result = await _submit(hass, result, details)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    subentry = next(iter(plain_entry.subentries.values()))
    assert subentry.data[CONF_BATTERY_ENTITY] is None


async def test_a_device_has_one_box(
    hass: HomeAssistant, box_one: dr.DeviceEntry
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NOTIFY_ENTITY: None},
        subentries_data=[box_subentry(hass, box_one, 1, PLAYERS_ONE)],
    )
    entry.add_to_hass(hass)
    result = await _start(hass, entry)
    result = await _submit(hass, result, {CONF_DEVICE_ID: box_one.id})
    assert result["step_id"] == "device"
    assert result["errors"] == {CONF_DEVICE_ID: "device_taken"}


@pytest.mark.parametrize(
    ("change", "field", "error"),
    [
        ({CONF_MQTT_PREFIX: "audio box"}, CONF_MQTT_PREFIX, "invalid_prefix"),
        ({CONF_MQTT_PREFIX: "audiobox/#"}, CONF_MQTT_PREFIX, "invalid_prefix"),
        ({CONF_MQTT_PREFIX: "/audiobox"}, CONF_MQTT_PREFIX, "invalid_prefix"),
        ({CONF_MA_USER: "  "}, CONF_MA_USER, "ma_user_required"),
        ({CONF_NAME: " "}, CONF_NAME, "name_required"),
        ({CONF_PLAYERS: []}, CONF_PLAYERS, "no_players"),
        (
            {CONF_PLAYERS: [_player(BOX_PLAYER, "Box"), _player(KIDS_ROOM, "Box ")]},
            CONF_PLAYERS,
            "duplicate_player_name",
        ),
    ],
)
async def test_details_errors(
    hass: HomeAssistant,
    plain_entry: MockConfigEntry,
    box_one: dr.DeviceEntry,
    change: dict[str, Any],
    field: str,
    error: str,
) -> None:
    result = await _start(hass, plain_entry)
    result = await _submit(hass, result, {CONF_DEVICE_ID: box_one.id})
    result = await _submit(hass, result, DETAILS | change)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "details"
    assert result["errors"] == {field: error}


async def test_reconfigure_shows_entity_ids(
    hass: HomeAssistant, box_one: dr.DeviceEntry
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NOTIFY_ENTITY: None},
        subentries_data=[box_subentry(hass, box_one, 1, PLAYERS_ONE)],
    )
    entry.add_to_hass(hass)
    subentry = next(iter(entry.subentries.values()))

    result = await entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    assert result["step_id"] == "device"
    assert suggested(result, CONF_DEVICE_ID) == box_one.id

    result = await _submit(hass, result, {CONF_DEVICE_ID: box_one.id})
    assert result["step_id"] == "details"
    assert suggested(result, CONF_NAME) == "Box 1"
    assert suggested(result, CONF_CARD_ENTITY) == "sensor.audiobox_1_card"
    assert suggested(result, CONF_PLAYERS)[1] == _player(KIDS_ROOM, "Kids room", "blue")

    result = await _submit(hass, result, DETAILS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[subentry.subentry_id].title == "Kids box"
