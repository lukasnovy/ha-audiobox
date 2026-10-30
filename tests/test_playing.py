"""Playback without a card, from the Music Assistant app: the box's controls work."""

from datetime import timedelta
import json

from freezegun.api import FrozenDateTimeFactory

from homeassistant.const import STATE_IDLE, STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.typing import MqttMockHAClient

from .common import (
    BOOK_UID,
    BOX_PLAYER,
    KIDS_ROOM,
    PLAYLIST_UID,
    RED,
    SELECT,
    Services,
    insert,
    remove,
    settle,
)

BUTTON_TOPIC = "audiobox1/event/button"
PLAYING_TOPIC = "audiobox1/playing"


async def _press(hass: HomeAssistant, button: str, **extra: int) -> None:
    async_fire_mqtt_message(hass, BUTTON_TOPIC, json.dumps({"button": button, **extra}))
    await settle(hass)


async def _player(hass: HomeAssistant, state: str, entity_id: str = BOX_PLAYER) -> None:
    hass.states.async_set(
        entity_id,
        state,
        {
            "media_position": 100,
            "media_duration": 3600,
            "media_position_updated_at": dt_util.utcnow(),
        },
    )
    await settle(hass)


async def _later(hass: HomeAssistant, minutes: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await settle(hass)


def _shown(mqtt_mock: MqttMockHAClient) -> list[str]:
    """What box 1 was told, in order."""
    return [
        call.args[1]
        for call in mqtt_mock.async_publish.call_args_list
        if call.args[0] == PLAYING_TOPIC
    ]


async def test_play_pause_while_playing(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _player(hass, STATE_PLAYING)
    await _press(hass, "playpause")
    [call] = services["media_player.media_play_pause"]
    assert call.data == {"entity_id": BOX_PLAYER}
    assert services.led_colours() == []


async def test_seek_while_playing(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _player(hass, STATE_PLAYING)
    await _press(hass, "fwd")
    [seek] = services["media_player.media_seek"]
    assert abs(seek.data["seek_position"] - 130) <= 1


async def test_restart_while_playing(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _player(hass, STATE_PLAYING)
    await _press(hass, "back_restart")
    [seek] = services["media_player.media_seek"]
    assert seek.data == {"entity_id": BOX_PLAYER, "seek_position": 1}


async def test_a_paused_player_holds_for_ten_minutes(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _player(hass, STATE_PLAYING)
    await _player(hass, STATE_PAUSED)
    await _later(hass, 9)
    await _press(hass, "playpause")
    assert len(services["media_player.media_play_pause"]) == 1

    await _later(hass, 10.1)
    await _press(hass, "playpause")
    assert len(services["media_player.media_play_pause"]) == 1
    assert services.led_colours() == [RED]


async def test_playing_again_restarts_the_hold(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    services: Services,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _player(hass, STATE_PLAYING)
    await _player(hass, STATE_PAUSED)
    freezer.tick(timedelta(minutes=8))
    async_fire_time_changed(hass)
    await _player(hass, STATE_PLAYING)
    await _player(hass, STATE_PAUSED)
    freezer.tick(timedelta(minutes=8))
    async_fire_time_changed(hass)
    await settle(hass)
    await _press(hass, "playpause")
    assert len(services["media_player.media_play_pause"]) == 1


async def test_stopped_is_not_playing(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _player(hass, STATE_PLAYING)
    await _player(hass, STATE_IDLE)
    await _press(hass, "playpause")
    assert services["media_player.media_play_pause"] == []
    assert services.led_colours() == [RED]


async def test_the_card_out_pause_holds_nothing(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await remove(hass)
    assert hass.states.is_state(BOX_PLAYER, STATE_PAUSED)
    await _press(hass, "playpause")
    assert services["media_player.media_play_pause"] == []


async def test_a_pause_with_a_card_holds_nothing_after_it(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await _player(hass, STATE_PAUSED)
    await remove(hass)
    await _press(hass, "playpause")
    assert services["media_player.media_play_pause"] == []


async def test_a_card_ends_a_running_hold(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    services: Services,
    mqtt_mock: MqttMockHAClient,
) -> None:
    await _player(hass, STATE_PLAYING)
    await _player(hass, STATE_PAUSED)
    # An unknown card plays nothing, so the player stays paused.
    await insert(hass, "04-ff-ff-ff")
    await remove(hass)
    assert _shown(mqtt_mock)[-1] == "OFF"
    await _press(hass, "playpause")
    assert services["media_player.media_play_pause"] == []


async def test_another_player_is_not_the_selected_one(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _player(hass, STATE_PLAYING, KIDS_ROOM)
    await _press(hass, "playpause")
    assert services["media_player.media_play_pause"] == []

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Kids room"},
        blocking=True,
    )
    await settle(hass)
    await _press(hass, "playpause")
    [call] = services["media_player.media_play_pause"]
    assert call.data == {"entity_id": KIDS_ROOM}


async def test_pick_a_player_while_playing(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _player(hass, STATE_PLAYING)
    await _press(hass, "select_player", player=1)
    [transfer] = services["music_assistant.transfer_queue"]
    assert transfer.data["entity_id"] == KIDS_ROOM
    assert hass.states.get(SELECT).state == "Kids room"


async def test_the_box_is_told(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    services: Services,
    mqtt_mock: MqttMockHAClient,
) -> None:
    assert _shown(mqtt_mock) == ["OFF"]
    await _player(hass, STATE_PLAYING)
    await _player(hass, STATE_PAUSED)
    assert _shown(mqtt_mock) == ["OFF", "ON"]
    await _later(hass, 10.1)
    assert _shown(mqtt_mock) == ["OFF", "ON", "OFF"]
    [call] = [
        call
        for call in mqtt_mock.async_publish.call_args_list
        if call.args[0] == PLAYING_TOPIC
    ][:1]
    assert call.args[2:] == (1, True)


async def test_the_box_goes_dark_with_the_card(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    services: Services,
    mqtt_mock: MqttMockHAClient,
) -> None:
    await insert(hass, PLAYLIST_UID)
    assert _shown(mqtt_mock)[-1] == "ON"
    await remove(hass)
    assert _shown(mqtt_mock)[-1] == "OFF"
