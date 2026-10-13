"""Play/pause, back and forward over MQTT."""

from datetime import timedelta
import json

import pytest

from homeassistant.const import STATE_PAUSED, STATE_PLAYING
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_mqtt_message,
)

from .common import BOOK_UID, BOX_PLAYER, PLAYLIST_UID, RED, Services, insert, settle

TOPIC = "audiobox1/event/button"


async def _press(hass: HomeAssistant, button: str) -> None:
    async_fire_mqtt_message(hass, TOPIC, json.dumps({"button": button}))
    await settle(hass)


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


async def test_back_stops_at_zero(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    _position(hass, STATE_PAUSED, 10)
    await _press(hass, "back")
    assert services["media_player.media_seek"][0].data["seek_position"] == 0


async def test_playlists_skip_tracks(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, PLAYLIST_UID)
    await _press(hass, "fwd")
    await _press(hass, "back")
    assert len(services["media_player.media_next_track"]) == 1
    assert len(services["media_player.media_previous_track"]) == 1
    assert services["media_player.media_seek"] == []


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
