"""Card in the tray: play, resume, refuse."""

from datetime import timedelta

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import STATE_PAUSED, STATE_PLAYING, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.audiobox.const import (
    CONF_NOTIFY_ENTITY,
    CONF_UID,
    DOMAIN,
    SUBENTRY_CARD,
)

from .common import (
    AMBER,
    BOOK_UID,
    BOOK_URI,
    BOX_PLAYER,
    CARD,
    GREEN,
    MA_USER,
    PLAYERS_ONE,
    PLAYLIST_UID,
    PLAYLIST_URI,
    RED,
    Services,
    box_subentry,
    card_subentry,
    insert,
    settle,
    suggested,
)


async def test_plays_the_book_as_the_ma_user(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    [call] = services["music_assistant.play_media"]
    assert call.data == {
        "entity_id": BOX_PLAYER,
        "media_id": BOOK_URI,
        "enqueue": "replace",
        "username": MA_USER,
    }
    assert services.led_colours() == [GREEN]


async def test_uid_case_and_whitespace(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, " 04-A2-3F-91 ")
    assert len(services["music_assistant.play_media"]) == 1


async def test_same_card_resumes_in_place(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    hass.states.async_set(CARD, "none")
    hass.states.async_set(BOX_PLAYER, STATE_PAUSED)
    await settle(hass)
    await insert(hass, BOOK_UID)
    assert len(services["music_assistant.play_media"]) == 1
    assert len(services["media_player.media_play"]) == 1


async def test_swap_pauses_first_and_shuffles_playlists(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    await insert(hass, PLAYLIST_UID)
    assert len(services["media_player.media_pause"]) == 1
    assert [c.data["media_id"] for c in services["music_assistant.play_media"]] == [
        BOOK_URI,
        PLAYLIST_URI,
    ]
    [shuffle] = services["media_player.shuffle_set"]
    assert shuffle.data == {"entity_id": BOX_PLAYER, "shuffle": True}


async def test_unknown_card(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, "04-99-99-99")
    assert services["music_assistant.play_media"] == []
    assert services.led_colours() == [RED]
    [note] = services["persistent_notification.create"]
    assert note.data["title"] == "Box 1: Unknown card"
    assert "04-99-99-99" in note.data["message"]
    assert loaded.runtime_data.last_unknown_uid == "04-99-99-99"


async def test_unknown_card_is_offered_in_the_card_form(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    await insert(hass, "04-99-99-99")
    result = await hass.config_entries.subentries.async_init(
        (loaded.entry_id, SUBENTRY_CARD), context={"source": SOURCE_USER}
    )
    assert suggested(result, CONF_UID) == "04-99-99-99"


async def test_player_unavailable(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.states.async_set(BOX_PLAYER, STATE_UNAVAILABLE)
    await insert(hass, BOOK_UID)
    assert services["music_assistant.play_media"] == []
    assert services.led_colours() == [AMBER]


async def test_no_ma_user(
    hass: HomeAssistant,
    mqtt_mock: None,
    box_one: dr.DeviceEntry,
    players: list[str],
    services: Services,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NOTIFY_ENTITY: None},
        subentries_data=[
            box_subentry(hass, box_one, 1, PLAYERS_ONE, ma_user=""),
            card_subentry(BOOK_UID, BOOK_URI, "Book"),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await insert(hass, BOOK_UID)
    assert services["music_assistant.play_media"] == []
    assert services.led_colours() == [RED]
    [note] = services["persistent_notification.create"]
    assert note.data["title"] == "Box 1: Music Assistant user missing"


async def test_play_media_error(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    def refuse(call: ServiceCall) -> None:
        raise ServiceValidationError("unknown user")

    services.register("music_assistant", "play_media", refuse)
    await insert(hass, BOOK_UID)
    assert services.led_colours() == [RED]
    # Not remembered as the last card: the next insert loads again.
    services.register(
        "music_assistant", "play_media", services.set_state(STATE_PLAYING)
    )
    hass.states.async_set(CARD, "none")
    hass.states.async_set(BOX_PLAYER, STATE_PAUSED)
    await insert(hass, BOOK_UID)
    assert services["media_player.media_play"] == []


async def test_playback_not_started_in_time(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    services.register("music_assistant", "play_media")
    hass.states.async_set(CARD, BOOK_UID)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await settle(hass)
    assert services.led_colours() == [RED]


async def test_attribute_update_does_not_reload(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    hass.states.async_set(CARD, BOOK_UID, {"rssi": -60})
    await settle(hass)
    assert len(services["music_assistant.play_media"]) == 1


async def test_card_back_from_unavailable_plays(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.states.async_set(CARD, STATE_UNAVAILABLE)
    await settle(hass)
    await insert(hass, BOOK_UID)
    assert len(services["music_assistant.play_media"]) == 1
