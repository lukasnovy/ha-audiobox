"""Constants and helpers shared by the Audiobox tests."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import (
    CONF_NAME,
    STATE_IDLE,
    STATE_OFF,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiobox.const import (
    CONF_BATTERY_ENTITY,
    CONF_CARD_ENTITY,
    CONF_CARD_PRESENT_ENTITY,
    CONF_DEVICE_ID,
    CONF_LED_ENTITY,
    CONF_MA_USER,
    CONF_MEDIA,
    CONF_MQTT_PREFIX,
    CONF_PLAYER_COLOUR,
    CONF_PLAYER_ENTITY,
    CONF_PLAYER_NAME,
    CONF_PLAYERS,
    CONF_SHUFFLE,
    CONF_UID,
    CONF_VOLUME_ENTITY,
    SUBENTRY_BOX,
    SUBENTRY_CARD,
)

BOX_PLAYER = "media_player.audiobox_1"
KIDS_ROOM = "media_player.kids_room"
LIVING_ROOM = "media_player.living_room"
CARD = "sensor.audiobox_1_card"
CARD_PRESENT = "binary_sensor.audiobox_1_card_present"
VOLUME = "number.audiobox_1_volume"
BATTERY = "sensor.audiobox_1_battery"
LED = "light.audiobox_1_led"
SELECT = "select.audiobox_1_player"

BOOK_UID = "04-a2-3f-91"
BOOK_URI = "library://audiobook/12345"
PLAYLIST_UID = "04-b1-22-77"
PLAYLIST_URI = "library://playlist/7"
MA_USER = "child1"

PLAYERS_ONE = [
    (BOX_PLAYER, "Box", "white"),
    (KIDS_ROOM, "Kids room", "blue"),
    (LIVING_ROOM, "Living room", "purple"),
]

GREEN = [0, 255, 0]
RED = [255, 0, 0]
AMBER = [255, 150, 0]
BLUE = [0, 80, 255]


def register_box_device(hass: HomeAssistant, number: int) -> dr.DeviceEntry:
    """Register a box device the way MQTT discovery would, with its entities."""
    owner = MockConfigEntry(domain="test")
    owner.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id,
        identifiers={("test", f"box{number}")},
        name=f"Audiobox {number}",
    )
    ent_reg = er.async_get(hass)
    for domain, suffix, original_name, device_class, state in (
        ("sensor", "card", "Card", None, "none"),
        ("binary_sensor", "card_present", "Card Present", None, STATE_OFF),
        ("number", "volume", "Volume", None, "25"),
        ("sensor", "battery", "Battery", "battery", "80"),
        ("light", "led", "LED", None, STATE_OFF),
    ):
        entity = ent_reg.async_get_or_create(
            domain,
            "test",
            f"box{number}_{suffix}",
            suggested_object_id=f"audiobox_{number}_{suffix}",
            device_id=device.id,
            original_name=original_name,
            original_device_class=device_class,
            config_entry=owner,
        )
        hass.states.async_set(entity.entity_id, state)
    return device


def register_player(hass: HomeAssistant, object_id: str) -> str:
    """Register an idle Music Assistant player."""
    entity = er.async_get(hass).async_get_or_create(
        "media_player", "test", object_id, suggested_object_id=object_id
    )
    hass.states.async_set(entity.entity_id, STATE_IDLE)
    return entity.entity_id


def box_subentry(
    hass: HomeAssistant,
    device: dr.DeviceEntry,
    number: int,
    players: list[tuple[str, str, str]],
    ma_user: str = MA_USER,
) -> ConfigSubentryData:
    """Box subentry data as the box form stores it: registry IDs."""
    ent_reg = er.async_get(hass)

    def rid(entity_id: str) -> str:
        entry = ent_reg.async_get(entity_id)
        assert entry is not None, entity_id
        return entry.id

    data = {
        CONF_DEVICE_ID: device.id,
        CONF_NAME: f"Box {number}",
        CONF_MQTT_PREFIX: f"audiobox{number}",
        CONF_MA_USER: ma_user,
        CONF_CARD_ENTITY: rid(f"sensor.audiobox_{number}_card"),
        CONF_CARD_PRESENT_ENTITY: rid(f"binary_sensor.audiobox_{number}_card_present"),
        CONF_VOLUME_ENTITY: rid(f"number.audiobox_{number}_volume"),
        CONF_BATTERY_ENTITY: rid(f"sensor.audiobox_{number}_battery"),
        CONF_LED_ENTITY: rid(f"light.audiobox_{number}_led"),
        CONF_PLAYERS: [
            {
                CONF_PLAYER_ENTITY: rid(entity_id),
                CONF_PLAYER_NAME: name,
                CONF_PLAYER_COLOUR: colour,
            }
            for entity_id, name, colour in players
        ],
    }
    return ConfigSubentryData(
        data=data, subentry_type=SUBENTRY_BOX, title=f"Box {number}", unique_id=device.id
    )


def media(uri: str, title: str) -> dict[str, Any]:
    """A media selector value as the Music Assistant browser returns it."""
    return {
        "entity_id": BOX_PLAYER,
        "media_content_id": uri,
        "media_content_type": "music",
        "metadata": {"title": title},
    }


def card_subentry(
    uid: str, uri: str, name: str, shuffle: bool = False
) -> ConfigSubentryData:
    """Card subentry data as the card form stores it."""
    return ConfigSubentryData(
        data={
            CONF_UID: uid,
            CONF_NAME: name,
            CONF_MEDIA: media(uri, name),
            CONF_SHUFFLE: shuffle,
        },
        subentry_type=SUBENTRY_CARD,
        title=name,
        unique_id=uid,
    )


def suggested(result: FlowResult, field: str) -> Any:
    """Return the suggested value of a form field."""
    for key in result["data_schema"].schema:
        if key == field:
            return (key.description or {}).get("suggested_value")
    raise KeyError(field)


class Services:
    """Mock actions. `calls["domain.service"]` lists the calls made."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Register every action the integration calls."""
        self.hass = hass
        self.calls: dict[str, list[ServiceCall]] = defaultdict(list)
        self.register("music_assistant", "play_media", self.set_state(STATE_PLAYING))
        self.register("music_assistant", "transfer_queue", self._transfer)
        self.register("media_player", "media_play", self.set_state(STATE_PLAYING))
        self.register("media_player", "media_pause", self.set_state(STATE_PAUSED))
        self.register("media_player", "media_stop", self.set_state(STATE_IDLE))
        for service in (
            "media_play_pause",
            "media_seek",
            "media_next_track",
            "media_previous_track",
            "volume_set",
            "shuffle_set",
        ):
            self.register("media_player", service)
        self.register("light", "turn_on")
        self.register("light", "turn_off")
        self.register("notify", "send_message")
        self.register("persistent_notification", "create")

    def register(
        self,
        domain: str,
        service: str,
        effect: Callable[[ServiceCall], None] | None = None,
    ) -> None:
        """Register (or replace) a mock action with an optional side effect."""

        @callback
        def handler(call: ServiceCall) -> None:
            self.calls[f"{domain}.{service}"].append(call)
            if effect is not None:
                effect(call)

        self.hass.services.async_register(domain, service, handler)

    def set_state(self, state: str) -> Callable[[ServiceCall], None]:
        """Side effect: the called player goes to `state`."""

        @callback
        def effect(call: ServiceCall) -> None:
            entity_id = call.data["entity_id"]
            old = self.hass.states.get(entity_id)
            self.hass.states.async_set(
                entity_id, state, old.attributes if old else None
            )

        return effect

    @callback
    def _transfer(self, call: ServiceCall) -> None:
        self.hass.states.async_set(
            call.data["entity_id"],
            STATE_PLAYING if call.data["auto_play"] else STATE_PAUSED,
        )
        self.hass.states.async_set(call.data["source_player"], STATE_IDLE)

    def __getitem__(self, key: str) -> list[ServiceCall]:
        """Calls made to `domain.service`."""
        return self.calls[key]

    def led_colours(self) -> list[list[int]]:
        """Colours sent to any LED, in order."""
        return [call.data["rgb_color"] for call in self.calls["light.turn_on"]]


async def settle(hass: HomeAssistant) -> None:
    """Let event handling and its background tasks finish."""
    await hass.async_block_till_done(wait_background_tasks=True)


async def insert(hass: HomeAssistant, uid: str) -> None:
    """Put a card in box 1's tray."""
    hass.states.async_set(CARD_PRESENT, STATE_ON)
    hass.states.async_set(CARD, uid)
    await settle(hass)


async def remove(hass: HomeAssistant) -> None:
    """Take the card out of box 1's tray."""
    hass.states.async_set(CARD_PRESENT, STATE_OFF)
    hass.states.async_set(CARD, "none")
    await settle(hass)
