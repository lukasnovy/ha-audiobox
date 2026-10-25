"""Runtime data and entity helpers for the Audiobox integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.hass_dict import HassKey

from .const import (
    CONF_BATTERY_ENTITY,
    CONF_CARD_ENTITY,
    CONF_CARD_PRESENT_ENTITY,
    CONF_DEVICE_ID,
    CONF_LED_ENTITY,
    CONF_MA_USER,
    CONF_MQTT_PREFIX,
    CONF_PLAYER_COLOUR,
    CONF_PLAYER_ENTITY,
    CONF_PLAYER_NAME,
    CONF_PLAYERS,
    CONF_VOLUME_ENTITY,
    DOMAIN,
)

if TYPE_CHECKING:
    from .box import BoxController

_LOGGER = logging.getLogger(__name__)


def to_registry_id(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Return the registry ID of an entity, so a rename does not break it.

    Entities without a registry entry are stored by entity ID.
    """
    if not entity_id:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    return entry.id if entry else entity_id


def resolve_entity(hass: HomeAssistant, value: str | None) -> str | None:
    """Return the entity ID for a stored registry ID or entity ID."""
    if not value:
        return None
    return er.async_resolve_entity_id(er.async_get(hass), value)


@dataclass(frozen=True, slots=True)
class PlayerConfig:
    """A player a box can move playback to."""

    entity_id: str
    name: str
    colour: str


@dataclass(frozen=True, slots=True)
class BoxConfig:
    """A box subentry with its entities resolved to entity IDs."""

    subentry_id: str
    device_id: str
    name: str
    mqtt_prefix: str
    ma_user: str
    card_entity: str | None
    card_present_entity: str | None
    volume_entity: str | None
    battery_entity: str | None
    led_entity: str | None
    players: tuple[PlayerConfig, ...]


@dataclass
class AudioboxRuntime:
    """What the loaded entry keeps."""

    snapshot: dict[str, Any]
    boxes: dict[str, BoxController] = field(default_factory=dict)
    last_unknown_uid: str | None = None


type AudioboxConfigEntry = ConfigEntry[AudioboxRuntime]


@dataclass(frozen=True, slots=True)
class Tap:
    """A card put on a box, known or not."""

    uid: str
    box_subentry_id: str
    box_name: str
    at: datetime


@dataclass
class AudioboxData:
    """What the integration keeps across entry reloads, for the pairing panel."""

    last_tap: Tap | None = None
    panel_subscribers: int = 0
    # Cover key -> URL fetched by the cover view.
    covers: dict[str, str] = field(default_factory=dict)
    # Media URI -> Music Assistant image URL, for a paired card's thumbnail.
    images: dict[str, str] = field(default_factory=dict)


DATA_AUDIOBOX: HassKey[AudioboxData] = HassKey(DOMAIN)


def domain_data(hass: HomeAssistant) -> AudioboxData:
    """Return the integration's data, created in `async_setup`."""
    return hass.data[DATA_AUDIOBOX]


def box_config_from_subentry(
    hass: HomeAssistant, subentry: ConfigSubentry
) -> BoxConfig:
    """Resolve a box subentry. A deleted entity is logged and left out."""
    data: Mapping[str, Any] = subentry.data
    name: str = data[CONF_NAME]

    def entity(key: str) -> str | None:
        value = data.get(key)
        resolved = resolve_entity(hass, value)
        if value and resolved is None:
            _LOGGER.warning("%s: the configured %s entity no longer exists", name, key)
        return resolved

    players: list[PlayerConfig] = []
    for player in data.get(CONF_PLAYERS, []):
        entity_id = resolve_entity(hass, player[CONF_PLAYER_ENTITY])
        if entity_id is None:
            _LOGGER.warning(
                "%s: player %s no longer exists", name, player[CONF_PLAYER_NAME]
            )
            continue
        players.append(
            PlayerConfig(entity_id, player[CONF_PLAYER_NAME], player[CONF_PLAYER_COLOUR])
        )

    return BoxConfig(
        subentry_id=subentry.subentry_id,
        device_id=data[CONF_DEVICE_ID],
        name=name,
        mqtt_prefix=data[CONF_MQTT_PREFIX],
        ma_user=data.get(CONF_MA_USER, ""),
        card_entity=entity(CONF_CARD_ENTITY),
        card_present_entity=entity(CONF_CARD_PRESENT_ENTITY),
        volume_entity=entity(CONF_VOLUME_ENTITY),
        battery_entity=entity(CONF_BATTERY_ENTITY),
        led_entity=entity(CONF_LED_ENTITY),
        players=tuple(players),
    )
