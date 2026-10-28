"""Play/pause, back and forward over MQTT."""

import asyncio
from datetime import timedelta
import json

import pytest

from homeassistant.const import STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
    async_fire_time_changed,
)

from .common import (
    BOOK_UID,
    BOX_PLAYER,
    GREEN,
    PLAYLIST_UID,
    RED,
    Services,
    insert,
    settle,
)

TOPIC = "audiobox1/event/button"


async def _press(hass: HomeAssistant, button: str) -> None:
    async_fire_mqtt_message(hass, TOPIC, json.dumps({"button": button}))
    await settle(hass)


def _press_now(hass: HomeAssistant, button: str) -> None:
    """Press without waiting for the job, so it is still running."""
    async_fire_mqtt_message(hass, TOPIC, json.dumps({"button": button}))


def _hold_seeks(hass: HomeAssistant, services: Services) -> asyncio.Event:
    """Make every media_seek wait until the returned event is set."""
    release = asyncio.Event()

    async def seek(call: ServiceCall) -> None:
        services.calls["media_player.media_seek"].append(call)
        await release.wait()

    hass.services.async_register("media_player", "media_seek", seek)
    return release


def _position(
    hass: HomeAssistant,
    state: str,
    position: float,
    age: float = 0,
    duration: float = 3600,
) -> None:
    hass.states.async_set(
        BOX_PLAYER,
        state,
        {
            "media_position": position,
            "media_duration": duration,
            "media_position_updated_at": dt_util.utcnow() - timedelta(seconds=age),
        },
    )


async def test_play_pause_with_a_card(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await _press(hass, "playpause")
    [call] = services["media_player.media_play_pause"]
    assert call.data == {"entity_id": BOX_PLAYER}


async def test_play_pause_without_a_card(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _press(hass, "playpause")
    assert services["media_player.media_play_pause"] == []
    assert services.led_colours() == [RED]


async def test_back_corrects_for_drift(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _position(hass, STATE_PLAYING, 100, age=5)
    await _press(hass, "back")
    [seek] = services["media_player.media_seek"]
    assert seek.data["seek_position"] == pytest.approx(75, abs=1)


async def test_forward_stops_short_of_the_end(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _position(hass, STATE_PAUSED, 3590)
    await _press(hass, "fwd")
    assert services["media_player.media_seek"][0].data["seek_position"] == 3595


async def test_back_stops_at_the_start(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _position(hass, STATE_PAUSED, 10)
    await _press(hass, "back")
    # Not 0: Music Assistant would resume the book where it left off.
    assert services["media_player.media_seek"][0].data["seek_position"] == 1


async def test_playlists_skip_tracks(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, PLAYLIST_UID)
    await _press(hass, "fwd")
    await _press(hass, "back")
    assert len(services["media_player.media_next_track"]) == 1
    assert len(services["media_player.media_previous_track"]) == 1
    assert services["media_player.media_seek"] == []


async def test_restart_seeks_to_the_beginning(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _position(hass, STATE_PLAYING, 2000)
    await _press(hass, "back_restart")
    [seek] = services["media_player.media_seek"]
    assert seek.data == {"entity_id": BOX_PLAYER, "seek_position": 1}


async def test_playlists_ignore_restart(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, PLAYLIST_UID)
    await _press(hass, "back_restart")
    assert services["media_player.media_seek"] == []
    assert services["media_player.media_previous_track"] == []


async def test_presses_during_a_seek_are_dropped(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    release = _hold_seeks(hass, services)
    _press_now(hass, "fwd")
    await hass.async_block_till_done()
    _press_now(hass, "fwd")
    _press_now(hass, "back")
    _press_now(hass, "back_restart")
    await hass.async_block_till_done()
    release.set()
    await settle(hass)
    assert len(services["media_player.media_seek"]) == 1


async def test_a_press_after_the_seek_is_taken(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await _press(hass, "fwd")
    await _press(hass, "fwd")
    assert len(services["media_player.media_seek"]) == 2


async def test_a_press_after_a_failed_seek_is_taken(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    def fail(call: ServiceCall) -> None:
        raise HomeAssistantError("Timeout waiting for audio data")

    services.register("media_player", "media_seek", fail)
    await insert(hass, BOOK_UID)
    await _press(hass, "fwd")
    await _press(hass, "fwd")
    assert len(services["media_player.media_seek"]) == 2


async def test_play_pause_is_not_blocked_by_a_seek(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    release = _hold_seeks(hass, services)
    _press_now(hass, "fwd")
    await hass.async_block_till_done()
    _press_now(hass, "playpause")
    await hass.async_block_till_done()
    release.set()
    await settle(hass)
    assert len(services["media_player.media_play_pause"]) == 1


async def test_seek_without_a_card_blinks_red(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await _press(hass, "fwd")
    await _press(hass, "back_restart")
    assert services["media_player.media_seek"] == []
    assert services.led_colours() == [RED]

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=1.1))
    await settle(hass)
    await _press(hass, "back")
    assert services.led_colours() == [RED, RED]
    assert services["media_player.media_seek"] == []


async def test_playlist_skips_one_after_another(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, PLAYLIST_UID)
    for _ in range(3):
        await _press(hass, "fwd")
    assert len(services["media_player.media_next_track"]) == 3
    assert services.led_colours() == [GREEN]


@pytest.mark.parametrize(
    "payload",
    ["not json", '{"x": 1}', '["button"]', '"playpause"', '{"button": "dance"}'],
)
async def test_bad_payloads_are_ignored(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    services: Services,
    caplog: pytest.LogCaptureFixture,
    payload: str,
) -> None:
    async_fire_mqtt_message(hass, TOPIC, payload)
    await settle(hass)
    assert not any(services.calls.values())
    assert "Traceback" not in caplog.text
