"""Tests for the card validation shared by the form and the panel."""

import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiobox.cards import card_errors, find_card_subentry
from custom_components.audiobox.const import CONF_NOTIFY_ENTITY, CONF_UID, DOMAIN

from .common import BOOK_UID, BOOK_URI, card_subentry

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


def test_card_errors_ok(card_entry: MockConfigEntry) -> None:
    assert card_errors(card_entry, NEW_UID, "library://audiobook/9", None) == {}
    assert card_errors(card_entry, NEW_UID, "spotify://playlist/x", None) == {}


def test_card_errors_uid(card_entry: MockConfigEntry) -> None:
    assert card_errors(card_entry, "04-aa", BOOK_URI, None) == {"uid": "invalid_uid"}
    assert card_errors(card_entry, BOOK_UID, BOOK_URI, None) == {"uid": "uid_taken"}
    assert card_errors(card_entry, BOOK_UID, BOOK_URI, BOOK_UID) == {}


def test_card_errors_media(card_entry: MockConfigEntry) -> None:
    assert card_errors(card_entry, NEW_UID, "library://album/1", None) == {
        "media": "unsupported_media"
    }
    assert card_errors(card_entry, NEW_UID, "spotify://audiobook/1", None) == {
        "media": "not_library_audiobook"
    }


def test_find_card_subentry(card_entry: MockConfigEntry) -> None:
    subentry = find_card_subentry(card_entry, BOOK_UID.upper())
    assert subentry is not None
    assert subentry.data[CONF_UID] == BOOK_UID
    assert find_card_subentry(card_entry, NEW_UID) is None
