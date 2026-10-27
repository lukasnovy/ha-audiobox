"""The box shows the selected player's volume and colour; the knob sets that player."""

from datetime import timedelta
import json

from homeassistant.const import STATE_PLAYING
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import MqttMockHAClient

from custom_components.audiobox import const

from .common import (
    BOX_PLAYER,
    KIDS_ROOM,
    LIVING_ROOM,
    PLAYLIST_UID,
    SELECT,
    VOLUME,
    Services,
    insert,
    settle,
)

COLOUR_TOPIC = "audiobox1/player_colour"


def _volume(hass: HomeAssistant, player: str, level: float) -> None:
    """Report `player` at `level`, as Music Assistant does, keeping its state."""
    state = hass.states.get(player)
    assert state is not None
    hass.states.async_set(
        player, state.state, {**state.attributes, "volume_level": level}
    )


async def _hold(hass: HomeAssistant) -> None:
    async_fire_mqtt_message(
        hass, "audiobox1/event/button", json.dumps({"button": "encoder_hold"})
    )
    await settle(hass)


async def _select(hass: HomeAssistant, option: str) -> None:
    await hass.services.async_call(
        "select", "select_option", {"entity_id": SELECT, "option": option}, blocking=True
    )
    await settle(hass)


async def _knob(hass: HomeAssistant, value: str) -> None:
    state = hass.states.get(VOLUME)
    hass.states.async_set(VOLUME, value, state.attributes if state else None)
    await settle(hass)


async def test_long_press_takes_the_new_players_volume(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, PLAYLIST_UID)
    _volume(hass, KIDS_ROOM, 0.2)
    await _knob(hass, "60")
    services.calls.clear()

    await _hold(hass)
    assert hass.states.get(SELECT).state == "Kids room"
    assert services["media_player.volume_set"] == []
    [shown] = services["number.set_value"]
    assert shown.data == {"entity_id": VOLUME, "value": 20}
    assert hass.states.get(VOLUME).state == "20"


async def test_long_press_sends_the_players_colour(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    services: Services,
    mqtt_mock: MqttMockHAClient,
) -> None:
    def colours() -> list[tuple[object, ...]]:
        return [
            call.args[1:4]
            for call in mqtt_mock.async_publish.call_args_list
            if call.args[0] == COLOUR_TOPIC
        ]

    assert colours() == [("255,255,255", 1, True)]
    await _hold(hass)
    assert colours()[-1] == ("0,80,255", 1, True)


async def test_player_without_a_volume_leaves_the_knob(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _hold(hass)
    assert services["number.set_value"] == []


async def test_volume_changed_elsewhere_moves_the_knob(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _select(hass, "Kids room")
    hass.states.async_set(KIDS_ROOM, STATE_PLAYING, {"volume_level": 0.35})
    await settle(hass)
    [shown] = services["number.set_value"]
    assert shown.data == {"entity_id": VOLUME, "value": 35}
    # Showing the player's own volume sends nothing back to it.
    assert services["media_player.volume_set"] == []


async def test_other_players_volume_is_ignored(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    _volume(hass, LIVING_ROOM, 0.5)
    await settle(hass)
    assert services["number.set_value"] == []


async def test_knob_is_not_pulled_back_by_a_late_report(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _knob(hass, "40")
    [sent] = services["media_player.volume_set"]
    assert sent.data == {"entity_id": BOX_PLAYER, "volume_level": 0.4}

    _volume(hass, BOX_PLAYER, 0.3)  # still on its way up from before the turn
    await settle(hass)
    _volume(hass, BOX_PLAYER, 0.4)
    await settle(hass)
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=const.KNOB_QUIET + 1)
    )
    await settle(hass)
    assert services["number.set_value"] == []

    _volume(hass, BOX_PLAYER, 0.5)  # someone in the Music Assistant app
    await settle(hass)
    assert services["number.set_value"][-1].data["value"] == 50


async def test_late_report_wins_once_the_knob_rests(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _knob(hass, "40")
    _volume(hass, BOX_PLAYER, 0.3)
    await settle(hass)
    assert services["number.set_value"] == []
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=const.KNOB_QUIET + 1)
    )
    await settle(hass)
    assert services["number.set_value"][-1].data["value"] == 30


async def test_volume_above_the_knob_ceiling_is_capped(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.states.async_set(VOLUME, "25", {"max": 90})
    await settle(hass)
    hass.states.async_set(KIDS_ROOM, STATE_PLAYING, {"volume_level": 0.95})
    await _select(hass, "Kids room")
    assert services["number.set_value"][-1].data["value"] == 90
    # The capped knob does not turn the player down to its own ceiling.
    assert all(
        call.data["entity_id"] != KIDS_ROOM
        for call in services["media_player.volume_set"]
    )
