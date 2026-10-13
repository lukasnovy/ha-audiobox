"""Config flow for Audiobox: the entry, boxes and cards."""

from __future__ import annotations

import logging
from typing import Any, override

import probatio

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    MediaSelector,
    MediaSelectorConfig,
    TextSelector,
)

from .cards import find_card, media_type_from_uri, normalize_uid
from .const import (
    CONF_MEDIA,
    CONF_NOTIFY_ENTITY,
    CONF_SHUFFLE,
    CONF_UID,
    DOMAIN,
    LIBRARY_AUDIOBOOK_PREFIX,
    MEDIA_TYPE_AUDIOBOOK,
    MEDIA_TYPE_PLAYLIST,
    SUBENTRY_CARD,
    UID_PATTERN,
)
from .models import resolve_entity, to_registry_id

_LOGGER = logging.getLogger(__name__)


def _entry_schema() -> probatio.Schema:
    return probatio.Schema(
        {
            probatio.Optional(CONF_NOTIFY_ENTITY): EntitySelector(
                EntitySelectorConfig(domain="notify")
            ),
        }
    )


def _entry_data(hass: HomeAssistant, user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_NOTIFY_ENTITY: to_registry_id(hass, user_input.get(CONF_NOTIFY_ENTITY))
    }


class AudioboxConfigFlow(ConfigFlow, domain=DOMAIN):
    """The Audiobox entry: global settings only."""

    VERSION = 1

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types: boxes and cards."""
        return {SUBENTRY_CARD: CardSubentryFlow}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry."""
        if user_input is not None:
            return self.async_create_entry(
                title="Audiobox", data=_entry_data(self.hass, user_input)
            )
        return self.async_show_form(step_id="user", data_schema=_entry_schema())

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the notification target."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            # The update listener reloads the entry because its data changed.
            return self.async_update_and_abort(
                entry, data=_entry_data(self.hass, user_input)
            )
        current = resolve_entity(self.hass, entry.data.get(CONF_NOTIFY_ENTITY))
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _entry_schema(), {CONF_NOTIFY_ENTITY: current} if current else {}
            ),
        )


CARD_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_UID): TextSelector(),
        probatio.Required(CONF_MEDIA): MediaSelector(MediaSelectorConfig()),
        probatio.Optional(CONF_NAME): TextSelector(),
        probatio.Optional(CONF_SHUFFLE, default=False): BooleanSelector(),
    }
)


def _card_data(
    entry: ConfigEntry, user_input: dict[str, Any], current_uid: str | None
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate the card form. Returns the data to store and the form errors."""
    errors: dict[str, str] = {}

    uid = normalize_uid(user_input[CONF_UID])
    if not UID_PATTERN.fullmatch(uid):
        errors[CONF_UID] = "invalid_uid"
    elif uid != current_uid and find_card(entry, uid) is not None:
        errors[CONF_UID] = "uid_taken"

    media = dict(user_input[CONF_MEDIA])
    media_id: str = media.get("media_content_id", "")
    media_type = media_type_from_uri(media_id)
    if media_type not in (MEDIA_TYPE_AUDIOBOOK, MEDIA_TYPE_PLAYLIST):
        errors[CONF_MEDIA] = "unsupported_media"
    elif media_type == MEDIA_TYPE_AUDIOBOOK and not media_id.startswith(
        LIBRARY_AUDIOBOOK_PREFIX
    ):
        # Plays, but never resumes: the one mistake that breaks the whole box.
        errors[CONF_MEDIA] = "not_library_audiobook"

    name = (
        (user_input.get(CONF_NAME) or "").strip()
        or (media.get("metadata") or {}).get("title")
        or media_id
    )
    data = {
        CONF_UID: uid,
        CONF_NAME: name,
        CONF_MEDIA: media,
        CONF_SHUFFLE: bool(user_input.get(CONF_SHUFFLE, False)),
    }
    return data, errors


class CardSubentryFlow(ConfigSubentryFlow):
    """Add or edit a card."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a card. The UID of the last unknown card is offered."""
        entry = self._get_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            _LOGGER.debug("Card form input: %s", user_input)
            data, errors = _card_data(entry, user_input, current_uid=None)
            if not errors:
                return self.async_create_entry(
                    title=data[CONF_NAME], data=data, unique_id=data[CONF_UID]
                )
            suggested_values: dict[str, Any] = user_input
        else:
            runtime = getattr(entry, "runtime_data", None)
            uid = getattr(runtime, "last_unknown_uid", None)
            known = uid is not None and find_card(entry, uid) is not None
            suggested_values = {CONF_UID: uid} if uid and not known else {}
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                CARD_SCHEMA, suggested_values
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit a card."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data, errors = _card_data(
                entry, user_input, current_uid=subentry.data[CONF_UID]
            )
            if not errors:
                return self.async_update_and_abort(
                    entry,
                    subentry,
                    data=data,
                    title=data[CONF_NAME],
                    unique_id=data[CONF_UID],
                )
            suggested_values: dict[str, Any] = user_input
        else:
            suggested_values = dict(subentry.data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                CARD_SCHEMA, suggested_values
            ),
            errors=errors,
        )
