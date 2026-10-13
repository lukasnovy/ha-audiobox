"""Card out: pause, then end the session after 10 minutes."""

from datetime import timedelta

from homeassistant.const import STATE_ON, STATE_PLAYING
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from .common import (
    BOOK_UID,
    BOX_PLAYER,
    CARD_PRESENT,
    KIDS_ROOM,
    SELECT,
    Services,
    insert,
    remove,
    settle,
)


async def _later(hass: HomeAssistant, minutes: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await settle(hass)


async def test_card_out_pauses(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await remove(hass)
    [pause] = services["media_player.media_pause"]
    assert pause.data == {"entity_id": BOX_PLAYER}
    assert services["light.turn_off"]
    assert services["media_player.media_stop"] == []


async def test_session_ends_after_ten_minutes(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": SELECT, "option": "Kids room"},
        blocking=True,
    )
    await insert(hass, BOOK_UID)
    await remove(hass)
    await _later(hass, 9)
    assert services["media_player.media_stop"] == []
    await _later(hass, 10.1)
    [stop] = services["media_player.media_stop"]
    assert stop.data == {"entity_id": KIDS_ROOM}
    assert hass.states.get(SELECT).state == "Box"


async def test_card_back_cancels_the_end(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await remove(hass)
    await _later(hass, 3)
    await insert(hass, BOOK_UID)
    await _later(hass, 11)
    assert services["media_player.media_stop"] == []
    assert hass.states.is_state(BOX_PLAYER, STATE_PLAYING)


async def test_end_is_skipped_while_a_card_is_present(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await remove(hass)
    hass.states.async_set(CARD_PRESENT, STATE_ON)
    await _later(hass, 11)
    assert services["media_player.media_stop"] == []


async def test_after_the_end_the_card_loads_again(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await remove(hass)
    await _later(hass, 11)
    await insert(hass, BOOK_UID)
    assert len(services["music_assistant.play_media"]) == 2
    assert services["media_player.media_play"] == []
