"""Tests for the card form."""

from types import SimpleNamespace
from typing import Any

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiobox.cards import find_card, media_type_from_uri
from custom_components.audiobox.const import (
    CONF_MEDIA,
    CONF_NOTIFY_ENTITY,
    CONF_SHUFFLE,
    CONF_UID,
    DOMAIN,
    SUBENTRY_CARD,
)

from .common import BOOK_UID, BOOK_URI, PLAYLIST_URI, card_subentry, media, suggested

pytestmark = pytest.mark.usefixtures("mqtt_mock")

NEW_UID = "04-aa-bb-cc"


@pytest.fixture
def card_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NOTIFY_ENTITY: None},
        subentries_data=[card_subentry(BOOK_UID, BOOK_URI, "Book")],
    )
    entry.add_to_hass(hass)
    return entry


async def _start(hass: HomeAssistant, entry: MockConfigEntry) -> Any:
    return await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_CARD), context={"source": SOURCE_USER}
    )


async def _submit(hass: HomeAssistant, result: Any, user_input: dict[str, Any]) -> Any:
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )


def test_media_type_from_uri() -> None:
    assert media_type_from_uri("library://audiobook/1") == "audiobook"
    assert media_type_from_uri("spotify://playlist/abc") == "playlist"
    assert media_type_from_uri("spotify:playlist:abc") is None
    assert media_type_from_uri("library://") is None


async def test_add_audiobook(hass: HomeAssistant, card_entry: MockConfigEntry) -> None:
    result = await _start(hass, card_entry)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    book = media("library://audiobook/999", "The Book")
    result = await _submit(hass, result, {CONF_UID: " 04-AA-BB-CC ", CONF_MEDIA: book})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "The Book"

    card = find_card(card_entry, NEW_UID)
    assert card is not None
    assert card.name == "The Book"
    assert card.media_id == "library://audiobook/999"
    assert card.media_type == "audiobook"
    assert card.shuffle is False
    subentry = next(
        s for s in card_entry.subentries.values() if s.unique_id == NEW_UID
    )
    assert subentry.data == {
        CONF_UID: NEW_UID,
        CONF_NAME: "The Book",
        CONF_MEDIA: book,
        CONF_SHUFFLE: False,
    }


async def test_given_name_wins_and_playlist_shuffles(
    hass: HomeAssistant, card_entry: MockConfigEntry
) -> None:
    result = await _start(hass, card_entry)
    result = await _submit(
        hass,
        result,
        {
            CONF_UID: NEW_UID,
            CONF_MEDIA: media(PLAYLIST_URI, "Songs"),
            CONF_NAME: " Morning ",
            CONF_SHUFFLE: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    card = find_card(card_entry, NEW_UID)
    assert card is not None
    assert (card.name, card.media_type, card.shuffle) == ("Morning", "playlist", True)


async def test_name_falls_back_to_uri(
    hass: HomeAssistant, card_entry: MockConfigEntry
) -> None:
    result = await _start(hass, card_entry)
    untitled = {**media(PLAYLIST_URI, "x"), "metadata": {}}
    result = await _submit(hass, result, {CONF_UID: NEW_UID, CONF_MEDIA: untitled})
    assert result["title"] == PLAYLIST_URI


@pytest.mark.parametrize(
    ("uid", "error"),
    [
        ("zz-01-02-03", "invalid_uid"),
        ("04-a2-3f", "invalid_uid"),
        ("04a23f91", "invalid_uid"),
        (BOOK_UID.upper(), "uid_taken"),
    ],
)
async def test_bad_uid(
    hass: HomeAssistant, card_entry: MockConfigEntry, uid: str, error: str
) -> None:
    result = await _start(hass, card_entry)
    result = await _submit(
        hass, result, {CONF_UID: uid, CONF_MEDIA: media("library://audiobook/5", "B")}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_UID: error}


@pytest.mark.parametrize(
    ("uri", "error"),
    [
        ("library://track/1", "unsupported_media"),
        ("media-source://media_source/local/a.mp3", "unsupported_media"),
        ("audiobookshelf--abc://audiobook/xyz", "not_library_audiobook"),
    ],
)
async def test_bad_media(
    hass: HomeAssistant, card_entry: MockConfigEntry, uri: str, error: str
) -> None:
    result = await _start(hass, card_entry)
    result = await _submit(hass, result, {CONF_UID: NEW_UID, CONF_MEDIA: media(uri, "X")})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_MEDIA: error}


async def test_prefills_last_unknown_uid(
    hass: HomeAssistant, card_entry: MockConfigEntry
) -> None:
    card_entry.runtime_data = SimpleNamespace(last_unknown_uid="04-11-22-33")
    result = await _start(hass, card_entry)
    assert suggested(result, CONF_UID) == "04-11-22-33"


async def test_no_prefill_for_a_known_uid(
    hass: HomeAssistant, card_entry: MockConfigEntry
) -> None:
    card_entry.runtime_data = SimpleNamespace(last_unknown_uid=BOOK_UID)
    result = await _start(hass, card_entry)
    assert suggested(result, CONF_UID) is None


async def test_reconfigure(hass: HomeAssistant, card_entry: MockConfigEntry) -> None:
    subentry = next(iter(card_entry.subentries.values()))
    result = await card_entry.start_subentry_reconfigure_flow(hass, subentry.subentry_id)
    assert result["step_id"] == "reconfigure"
    assert suggested(result, CONF_UID) == BOOK_UID
    assert suggested(result, CONF_MEDIA) == media(BOOK_URI, "Book")

    result = await _submit(
        hass,
        result,
        {CONF_UID: BOOK_UID, CONF_MEDIA: media(BOOK_URI, "Book"), CONF_NAME: "Renamed"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = card_entry.subentries[subentry.subentry_id]
    assert subentry.title == "Renamed"
    assert subentry.data[CONF_NAME] == "Renamed"


async def test_reconfigure_to_a_taken_uid(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NOTIFY_ENTITY: None},
        subentries_data=[
            card_subentry(BOOK_UID, BOOK_URI, "Book"),
            card_subentry(NEW_UID, PLAYLIST_URI, "Songs"),
        ],
    )
    entry.add_to_hass(hass)
    songs = next(s for s in entry.subentries.values() if s.unique_id == NEW_UID)
    result = await entry.start_subentry_reconfigure_flow(hass, songs.subentry_id)
    result = await _submit(
        hass, result, {CONF_UID: BOOK_UID, CONF_MEDIA: media(PLAYLIST_URI, "Songs")}
    )
    assert result["errors"] == {CONF_UID: "uid_taken"}
