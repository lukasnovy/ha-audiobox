"""Knob long-press moves playback; the knob sets the selected player's volume."""

from datetime import timedelta
import json

import pytest

from homeassistant.const import STATE_PAUSED, STATE_PLAYING, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from custom_components.audiobox.const import CONF_NOTIFY_ENTITY, DOMAIN

from .common import (
    AMBER,
    BLUE,
    BOOK_UID,
    BOOK_URI,
    BOX_PLAYER,
    KIDS_ROOM,
    LIVING_ROOM,
    MA_USER,
    PLAYERS_ONE,
    PLAYLIST_UID,
    RED,
    SELECT,
    VOLUME,
    Services,
    box_subentry,
    card_subentry,
    insert,
    register_box_device,
    register_player,
    settle,
)


async def _hold(hass: HomeAssistant, prefix: str = "audiobox1") -> None:
    async_fire_mqtt_message(
        hass, f"{prefix}/event/button", json.dumps({"button": "encoder_hold"})
    )
    await settle(hass)


async def _select(hass: HomeAssistant, entity_id: str, option: str) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": option},
        blocking=True,
    )


def _at(hass: HomeAssistant, player: str, state: str, position: float) -> None:
    """Give `player` a book position the way Music Assistant reports it."""
    hass.states.async_set(
        player,
        state,
        {
            "media_position": position,
            "media_duration": 3000,
            "media_position_updated_at": dt_util.utcnow(),
        },
    )


async def test_moves_a_playing_book_as_its_user(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _at(hass, BOX_PLAYER, STATE_PLAYING, 600)
    await _hold(hass)
    assert services["music_assistant.transfer_queue"] == []
    assert [call.data for call in services["media_player.media_pause"]] == [
        {"entity_id": BOX_PLAYER}
    ]
    assert [call.data for call in services["media_player.media_stop"]] == [
        {"entity_id": BOX_PLAYER}
    ]
    [_, play] = services["music_assistant.play_media"]
    assert play.data == {
        "entity_id": KIDS_ROOM,
        "media_id": BOOK_URI,
        "enqueue": "replace",
        "username": MA_USER,
    }
    [seek] = services["media_player.media_seek"]
    assert seek.data == {"entity_id": KIDS_ROOM, "seek_position": 600}
    assert hass.states.get(KIDS_ROOM).state == STATE_PLAYING
    assert hass.states.get(SELECT).state == "Kids room"
    [volume] = services["media_player.volume_set"]
    assert volume.data == {"entity_id": KIDS_ROOM, "volume_level": 0.25}
    assert services.led_colours()[-1] == BLUE


async def test_moves_a_paused_book_and_keeps_it_paused(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _at(hass, BOX_PLAYER, STATE_PAUSED, 600)
    await _hold(hass)
    assert [call.data for call in services["media_player.media_pause"]] == [
        {"entity_id": KIDS_ROOM}
    ]
    assert services["music_assistant.play_media"][-1].data["entity_id"] == KIDS_ROOM
    assert services["media_player.media_seek"][0].data["seek_position"] == 600
    assert hass.states.get(KIDS_ROOM).state == STATE_PAUSED
    assert hass.states.get(SELECT).state == "Kids room"


async def test_book_at_its_start_is_not_seeked(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _at(hass, BOX_PLAYER, STATE_PLAYING, 0)
    await _hold(hass)
    assert services["music_assistant.play_media"][-1].data["entity_id"] == KIDS_ROOM
    assert services["media_player.media_seek"] == []


async def test_book_near_its_end_is_not_finished(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _at(hass, BOX_PLAYER, STATE_PLAYING, 2999)
    await _hold(hass)
    assert services["media_player.media_seek"][0].data["seek_position"] == 2995


async def test_failed_book_move_keeps_the_selection(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _at(hass, BOX_PLAYER, STATE_PLAYING, 600)

    def refuse(call: ServiceCall) -> None:
        raise HomeAssistantError("no such user")

    services.register("music_assistant", "play_media", refuse)
    await _hold(hass)
    assert services["media_player.media_seek"] == []
    assert hass.states.get(SELECT).state == "Box"
    assert services.led_colours()[-1] == RED


async def test_book_that_does_not_start_keeps_the_selection(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _at(hass, BOX_PLAYER, STATE_PLAYING, 600)
    services.register("music_assistant", "play_media")
    async_fire_mqtt_message(
        hass, "audiobox1/event/button", json.dumps({"button": "encoder_hold"})
    )
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await settle(hass)
    assert services["media_player.media_seek"] == []
    assert hass.states.get(SELECT).state == "Box"
    assert services.led_colours()[-1] == RED


async def test_moves_a_playing_playlist(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, PLAYLIST_UID)
    await _hold(hass)
    [move] = services["music_assistant.transfer_queue"]
    assert move.data == {
        "entity_id": KIDS_ROOM,
        "source_player": BOX_PLAYER,
        "auto_play": True,
    }
    assert hass.states.get(SELECT).state == "Kids room"
    [volume] = services["media_player.volume_set"]
    assert volume.data == {"entity_id": KIDS_ROOM, "volume_level": 0.25}
    assert services.led_colours()[-1] == BLUE


async def test_moves_a_paused_playlist_without_playing(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, PLAYLIST_UID)
    hass.states.async_set(BOX_PLAYER, STATE_PAUSED)
    await _hold(hass)
    assert services["music_assistant.transfer_queue"][0].data["auto_play"] is False
    assert hass.states.get(SELECT).state == "Kids room"


async def test_nothing_loaded_only_selects(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _hold(hass)
    assert services["music_assistant.transfer_queue"] == []
    assert services["music_assistant.play_media"] == []
    assert hass.states.get(SELECT).state == "Kids room"


async def test_wraps_and_skips_unavailable(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _select(hass, SELECT, "Living room")
    hass.states.async_set(KIDS_ROOM, STATE_UNAVAILABLE)
    await _hold(hass)
    assert hass.states.get(SELECT).state == "Box"
    await _hold(hass)
    assert hass.states.get(SELECT).state == "Living room"


async def test_no_free_player(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.states.async_set(KIDS_ROOM, STATE_UNAVAILABLE)
    hass.states.async_set(LIVING_ROOM, STATE_UNAVAILABLE)
    await _hold(hass)
    assert hass.states.get(SELECT).state == "Box"
    assert services.led_colours() == [AMBER]


async def test_failed_playlist_move_keeps_the_selection(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, PLAYLIST_UID)
    services.register("music_assistant", "transfer_queue")
    async_fire_mqtt_message(
        hass, "audiobox1/event/button", json.dumps({"button": "encoder_hold"})
    )
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await settle(hass)
    assert hass.states.get(SELECT).state == "Box"
    assert services.led_colours()[-1] == RED


async def test_skips_a_player_another_box_has(
    hass: HomeAssistant,
    mqtt_mock: None,
    box_one: dr.DeviceEntry,
    players: list[str],
    services: Services,
) -> None:
    box_two = register_box_device(hass, 2)
    register_player(hass, "audiobox_2")
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NOTIFY_ENTITY: None},
        subentries_data=[
            box_subentry(hass, box_one, 1, PLAYERS_ONE),
            box_subentry(
                hass,
                box_two,
                2,
                [
                    ("media_player.audiobox_2", "Box", "white"),
                    (LIVING_ROOM, "Living room", "purple"),
                ],
            ),
            card_subentry(BOOK_UID, BOOK_URI, "Book"),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await _select(hass, "select.audiobox_2_player", "Living room")
    await _hold(hass)
    assert hass.states.get(SELECT).state == "Kids room"
    await _hold(hass)
    assert hass.states.get(SELECT).state == "Box"  # Living room skipped

    await _select(hass, "select.audiobox_2_player", "Box")
    await _hold(hass)
    await _hold(hass)
    assert hass.states.get(SELECT).state == "Living room"


async def test_knob_sets_the_selected_player(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _select(hass, SELECT, "Kids room")
    hass.states.async_set(VOLUME, "40")
    await settle(hass)
    [call] = services["media_player.volume_set"]
    assert call.data == {"entity_id": KIDS_ROOM, "volume_level": 0.4}


@pytest.mark.parametrize("value", ["unknown", "-1", "loud"])
async def test_knob_ignores_bad_values(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services, value: str
) -> None:
    hass.states.async_set(VOLUME, value)
    await settle(hass)
    assert services["media_player.volume_set"] == []
