"""Cards: which UID plays what."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_NAME

from .const import CONF_MEDIA, CONF_SHUFFLE, CONF_UID, SUBENTRY_CARD


@dataclass(frozen=True, slots=True)
class Card:
    """A card as the box needs it."""

    uid: str
    name: str
    media_id: str
    media_type: str | None
    shuffle: bool


def normalize_uid(raw: str) -> str:
    """Return a UID the way cards are stored: trimmed, lower case."""
    return raw.strip().lower()


def media_type_from_uri(uri: str) -> str | None:
    """Return the media type of a Music Assistant URI, `<provider>://<type>/<id>`.

    Music Assistant's media browser reports the content type `music` for every
    item, so the URI is the only reliable source.
    """
    _, separator, path = uri.partition("://")
    if not separator:
        return None
    media_type, _, _ = path.partition("/")
    return media_type or None


def card_from_subentry(subentry: ConfigSubentry) -> Card:
    """Build a card from its subentry."""
    media_id: str = subentry.data[CONF_MEDIA]["media_content_id"]
    return Card(
        uid=subentry.data[CONF_UID],
        name=subentry.data[CONF_NAME],
        media_id=media_id,
        media_type=media_type_from_uri(media_id),
        shuffle=subentry.data.get(CONF_SHUFFLE, False),
    )


def find_card(entry: ConfigEntry, uid: str) -> Card | None:
    """Return the card with this UID, or None."""
    uid = normalize_uid(uid)
    for subentry in entry.get_subentries_of_type(SUBENTRY_CARD):
        if subentry.data[CONF_UID] == uid:
            return card_from_subentry(subentry)
    return None
