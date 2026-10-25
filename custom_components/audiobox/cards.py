"""Cards: which UID plays what."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_NAME

from .const import (
    CONF_MEDIA,
    CONF_SHUFFLE,
    CONF_UID,
    LIBRARY_AUDIOBOOK_PREFIX,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_PLAYLIST,
    SUBENTRY_CARD,
    UID_PATTERN,
)


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


def find_card_subentry(entry: ConfigEntry, uid: str) -> ConfigSubentry | None:
    """Return the subentry of the card with this UID, or None."""
    uid = normalize_uid(uid)
    for subentry in entry.get_subentries_of_type(SUBENTRY_CARD):
        if subentry.data[CONF_UID] == uid:
            return subentry
    return None


def find_card(entry: ConfigEntry, uid: str) -> Card | None:
    """Return the card with this UID, or None."""
    subentry = find_card_subentry(entry, uid)
    return card_from_subentry(subentry) if subentry is not None else None


def card_errors(
    entry: ConfigEntry, uid: str, media_id: str, current_uid: str | None
) -> dict[str, str]:
    """Check a card before it is stored. Returns errors keyed `uid` and `media`.

    `uid` is normalised. `current_uid` is the UID of the card being edited.
    """
    errors: dict[str, str] = {}
    if not UID_PATTERN.fullmatch(uid):
        errors[CONF_UID] = "invalid_uid"
    elif uid != current_uid and find_card_subentry(entry, uid) is not None:
        errors[CONF_UID] = "uid_taken"

    media_type = media_type_from_uri(media_id)
    if media_type not in (MEDIA_TYPE_AUDIOBOOK, MEDIA_TYPE_PLAYLIST):
        errors[CONF_MEDIA] = "unsupported_media"
    elif media_type == MEDIA_TYPE_AUDIOBOOK and not media_id.startswith(
        LIBRARY_AUDIOBOOK_PREFIX
    ):
        # Plays, but never resumes: the one mistake that breaks the whole box.
        errors[CONF_MEDIA] = "not_library_audiobook"
    return errors
