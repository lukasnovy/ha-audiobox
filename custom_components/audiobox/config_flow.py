"""Config flow for Audiobox: the entry, boxes and cards."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
from typing import Any, override

import probatio

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    DeviceSelector,
    DeviceSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    MediaSelector,
    MediaSelectorConfig,
    ObjectSelector,
    ObjectSelectorConfig,
    TextSelector,
)
from homeassistant.util import slugify

from .cards import card_errors, find_card, normalize_uid
from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CARD_ENTITY,
    CONF_CARD_PRESENT_ENTITY,
    CONF_DEVICE_ID,
    CONF_LED_ENTITY,
    CONF_MA_USER,
    CONF_MEDIA,
    CONF_MQTT_PREFIX,
    CONF_NOTIFY_ENTITY,
    CONF_PLAYER_COLOUR,
    CONF_PLAYER_ENTITY,
    CONF_PLAYER_NAME,
    CONF_PLAYERS,
    CONF_SHUFFLE,
    CONF_UID,
    CONF_VOLUME_ENTITY,
    DOMAIN,
    ENTITY_KEYS,
    MQTT_PREFIX_PATTERN,
    PLAYER_COLOURS,
    SUBENTRY_BOX,
    SUBENTRY_CARD,
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
        return {SUBENTRY_BOX: BoxSubentryFlow, SUBENTRY_CARD: CardSubentryFlow}

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
    uid = normalize_uid(user_input[CONF_UID])
    media = dict(user_input[CONF_MEDIA])
    media_id: str = media.get("media_content_id", "")
    errors = card_errors(entry, uid, media_id, current_uid)

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


def _drop_automatic_name(
    stored: Mapping[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    """Let a name taken from the old book follow a newly picked book."""
    old_media = stored[CONF_MEDIA]
    old_title = (old_media.get("metadata") or {}).get("title") or old_media.get(
        "media_content_id"
    )
    name = (user_input.get(CONF_NAME) or "").strip()
    new_book = user_input[CONF_MEDIA].get("media_content_id") != old_media.get(
        "media_content_id"
    )
    if new_book and name == stored[CONF_NAME] == old_title:
        return {**user_input, CONF_NAME: ""}
    return user_input


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
            user_input = _drop_automatic_name(subentry.data, user_input)
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


DEVICE_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_DEVICE_ID): DeviceSelector(
            DeviceSelectorConfig(filter={"integration": "mqtt"})
        ),
    }
)


def _box_schema(hass: HomeAssistant, device_id: str) -> probatio.Schema:
    """The details form. Entity pickers offer the device's own entities."""
    entities = er.async_entries_for_device(er.async_get(hass), device_id)

    def picker(domain: str) -> EntitySelector:
        config = EntitySelectorConfig(domain=domain)
        own = [entity.entity_id for entity in entities if entity.domain == domain]
        if own:
            config["include_entities"] = own
        return EntitySelector(config)

    players = ObjectSelector(
        ObjectSelectorConfig(
            multiple=True,
            label_field=CONF_PLAYER_NAME,
            translation_key="player",
            fields={
                CONF_PLAYER_ENTITY: {
                    "selector": {"entity": {"filter": {"domain": "media_player"}}},
                    "required": True,
                    "label": "Player",
                },
                CONF_PLAYER_NAME: {
                    "selector": {"text": {}},
                    "required": True,
                    "label": "Name",
                },
                CONF_PLAYER_COLOUR: {
                    "selector": {
                        "select": {
                            "options": list(PLAYER_COLOURS),
                            "translation_key": "colour",
                        }
                    },
                    "required": True,
                    "label": "Colour",
                },
            },
        )
    )
    return probatio.Schema(
        {
            probatio.Required(CONF_NAME): TextSelector(),
            probatio.Required(CONF_MQTT_PREFIX): TextSelector(),
            probatio.Required(CONF_MA_USER): TextSelector(),
            probatio.Required(CONF_CARD_ENTITY): picker("sensor"),
            probatio.Required(CONF_CARD_PRESENT_ENTITY): picker("binary_sensor"),
            probatio.Required(CONF_VOLUME_ENTITY): picker("number"),
            probatio.Optional(CONF_BATTERY_ENTITY): picker("sensor"),
            probatio.Required(CONF_LED_ENTITY): picker("light"),
            probatio.Required(CONF_PLAYERS): players,
        }
    )


def _guess_box(hass: HomeAssistant, device_id: str) -> dict[str, Any]:
    """Best guesses for a new box, from the device and its entities."""
    device = dr.async_get(hass).async_get(device_id)
    # The prefix and the box's own player follow the firmware name, which a
    # rename in Home Assistant does not change.
    firmware_name = (device.name or "") if device else ""
    name = (device.name_by_user or firmware_name) if device else ""
    entities = er.async_entries_for_device(er.async_get(hass), device_id)

    def label(entity: er.RegistryEntry) -> str:
        return f"{entity.entity_id} {entity.original_name or ''} {entity.name or ''}".lower()

    def first(
        domain: str, test: Callable[[er.RegistryEntry], bool] = lambda _: True
    ) -> str | None:
        return next(
            (e.entity_id for e in entities if e.domain == domain and test(e)), None
        )

    guess: dict[str, Any] = {
        CONF_NAME: name,
        CONF_MQTT_PREFIX: firmware_name.lower().replace(" ", ""),
        CONF_CARD_ENTITY: first("sensor", lambda e: "card" in label(e)),
        CONF_CARD_PRESENT_ENTITY: first("binary_sensor", lambda e: "present" in label(e))
        or first("binary_sensor"),
        CONF_VOLUME_ENTITY: first("number"),
        CONF_BATTERY_ENTITY: first(
            "sensor",
            lambda e: (e.device_class or e.original_device_class) == "battery",
        )
        or first("sensor", lambda e: "battery" in label(e)),
        CONF_LED_ENTITY: first("light"),
    }
    # The box's own Music Assistant player is named like the box.
    own_player = f"media_player.{slugify(firmware_name)}" if firmware_name else None
    if own_player and (
        er.async_get(hass).async_get(own_player) or hass.states.get(own_player)
    ):
        guess[CONF_PLAYERS] = [
            {
                CONF_PLAYER_ENTITY: own_player,
                CONF_PLAYER_NAME: name,
                CONF_PLAYER_COLOUR: "white",
            }
        ]
    return {key: value for key, value in guess.items() if value}


def _box_form_values(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, Any]:
    """Stored box data, with registry IDs turned back into entity IDs."""
    values: dict[str, Any] = {
        CONF_NAME: data[CONF_NAME],
        CONF_MQTT_PREFIX: data[CONF_MQTT_PREFIX],
        CONF_MA_USER: data[CONF_MA_USER],
    }
    for key in ENTITY_KEYS:
        if entity_id := resolve_entity(hass, data.get(key)):
            values[key] = entity_id
    values[CONF_PLAYERS] = [
        {
            CONF_PLAYER_ENTITY: resolve_entity(hass, player[CONF_PLAYER_ENTITY])
            or player[CONF_PLAYER_ENTITY],
            CONF_PLAYER_NAME: player[CONF_PLAYER_NAME],
            CONF_PLAYER_COLOUR: player[CONF_PLAYER_COLOUR],
        }
        for player in data[CONF_PLAYERS]
    ]
    return values


def _validate_box(user_input: dict[str, Any]) -> dict[str, str]:
    """Errors in the details form."""
    errors: dict[str, str] = {}
    if not user_input[CONF_NAME].strip():
        errors[CONF_NAME] = "name_required"
    if not MQTT_PREFIX_PATTERN.fullmatch(user_input[CONF_MQTT_PREFIX].strip()):
        errors[CONF_MQTT_PREFIX] = "invalid_prefix"
    if not user_input[CONF_MA_USER].strip():
        errors[CONF_MA_USER] = "ma_user_required"
    players = user_input.get(CONF_PLAYERS) or []
    names = [player[CONF_PLAYER_NAME].strip() for player in players]
    if not players:
        errors[CONF_PLAYERS] = "no_players"
    elif "" in names or len(set(names)) != len(names):
        errors[CONF_PLAYERS] = "duplicate_player_name"
    return errors


def _box_data(
    hass: HomeAssistant, device_id: str, user_input: dict[str, Any]
) -> dict[str, Any]:
    """What to store: trimmed text, registry IDs for entities."""
    data: dict[str, Any] = {
        CONF_DEVICE_ID: device_id,
        CONF_NAME: user_input[CONF_NAME].strip(),
        CONF_MQTT_PREFIX: user_input[CONF_MQTT_PREFIX].strip(),
        CONF_MA_USER: user_input[CONF_MA_USER].strip(),
    }
    for key in ENTITY_KEYS:
        data[key] = to_registry_id(hass, user_input.get(key))
    data[CONF_PLAYERS] = [
        {
            CONF_PLAYER_ENTITY: to_registry_id(hass, player[CONF_PLAYER_ENTITY]),
            CONF_PLAYER_NAME: player[CONF_PLAYER_NAME].strip(),
            CONF_PLAYER_COLOUR: player[CONF_PLAYER_COLOUR],
        }
        for player in user_input[CONF_PLAYERS]
    ]
    return data


class BoxSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a box: pick its device, then the details."""

    def __init__(self) -> None:
        """Start without a device."""
        self._device_id: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a box."""
        return await self.async_step_device()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure a box."""
        return await self.async_step_device()

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Pick the box's device."""
        errors: dict[str, str] = {}
        if user_input is not None:
            device_id = user_input[CONF_DEVICE_ID]
            if self._device_taken(device_id):
                errors[CONF_DEVICE_ID] = "device_taken"
            else:
                self._device_id = device_id
                return await self.async_step_details()
        suggested_values: dict[str, Any] = {}
        if self.source == SOURCE_RECONFIGURE:
            suggested_values[CONF_DEVICE_ID] = self._get_reconfigure_subentry().data[
                CONF_DEVICE_ID
            ]
        return self.async_show_form(
            step_id="device",
            data_schema=self.add_suggested_values_to_schema(
                DEVICE_SCHEMA, suggested_values
            ),
            errors=errors,
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Name, MQTT prefix, MA user, entities and players."""
        assert self._device_id is not None
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_box(user_input)
            if not errors:
                data = _box_data(self.hass, self._device_id, user_input)
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_update_and_abort(
                        self._get_entry(),
                        self._get_reconfigure_subentry(),
                        data=data,
                        title=data[CONF_NAME],
                        unique_id=self._device_id,
                    )
                return self.async_create_entry(
                    title=data[CONF_NAME], data=data, unique_id=self._device_id
                )
            suggested_values: dict[str, Any] = user_input
        elif (
            self.source == SOURCE_RECONFIGURE
            and self._get_reconfigure_subentry().data[CONF_DEVICE_ID] == self._device_id
        ):
            suggested_values = _box_form_values(
                self.hass, self._get_reconfigure_subentry().data
            )
        else:
            suggested_values = _guess_box(self.hass, self._device_id)
        return self.async_show_form(
            step_id="details",
            data_schema=self.add_suggested_values_to_schema(
                _box_schema(self.hass, self._device_id), suggested_values
            ),
            errors=errors,
        )

    def _device_taken(self, device_id: str) -> bool:
        """Whether another box already uses this device."""
        own = (
            self._get_reconfigure_subentry().subentry_id
            if self.source == SOURCE_RECONFIGURE
            else None
        )
        return any(
            subentry.unique_id == device_id and subentry.subentry_id != own
            for subentry in self._get_entry().subentries.values()
        )
