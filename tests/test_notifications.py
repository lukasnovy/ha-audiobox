"""Low battery, offline, and where notifications go."""

from datetime import timedelta

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.audiobox.const import CONF_NOTIFY_ENTITY, DOMAIN

from .common import (
    BATTERY,
    BOOK_UID,
    BOOK_URI,
    CARD,
    PLAYERS_ONE,
    Services,
    box_subentry,
    card_subentry,
    insert,
    settle,
)


async def _later(hass: HomeAssistant, minutes: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await settle(hass)


async def test_battery_low_after_five_minutes(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.states.async_set(BATTERY, "15")
    await _later(hass, 4)
    assert services["persistent_notification.create"] == []
    await _later(hass, 5.1)
    [note] = services["persistent_notification.create"]
    assert note.data["title"] == "Box 1: Battery low"
    assert note.data["message"].startswith("15 %")


async def test_battery_recovering_cancels(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.states.async_set(BATTERY, "15")
    await settle(hass)
    hass.states.async_set(BATTERY, "60")
    await _later(hass, 6)
    assert services["persistent_notification.create"] == []


async def test_offline(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.states.async_set(CARD, STATE_UNAVAILABLE)
    await settle(hass)
    [note] = services["persistent_notification.create"]
    assert note.data["title"] == "Box 1: Offline"


async def test_no_offline_for_a_new_entity(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.states.async_remove(CARD)
    hass.states.async_set(CARD, STATE_UNAVAILABLE)
    await settle(hass)
    assert services["persistent_notification.create"] == []


async def test_notification_target(
    hass: HomeAssistant,
    mqtt_mock: None,
    box_one: dr.DeviceEntry,
    players: list[str],
    services: Services,
) -> None:
    phone = er.async_get(hass).async_get_or_create(
        "notify", "test", "phone", suggested_object_id="phone"
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NOTIFY_ENTITY: phone.id},
        subentries_data=[
            box_subentry(hass, box_one, 1, PLAYERS_ONE),
            card_subentry(BOOK_UID, BOOK_URI, "Book"),
        ],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await insert(hass, "04-99-99-99")
    [message] = services["notify.send_message"]
    assert message.data["entity_id"] == "notify.phone"
    assert message.data["title"] == "Box 1: Unknown card"
    assert services["persistent_notification.create"] == []


async def test_failing_target_falls_back(
    hass: HomeAssistant,
    mqtt_mock: None,
    box_one: dr.DeviceEntry,
    players: list[str],
    services: Services,
) -> None:
    def broken(call: ServiceCall) -> None:
        raise HomeAssistantError("push service down")

    services.register("notify", "send_message", broken)
    phone = er.async_get(hass).async_get_or_create(
        "notify", "test", "phone", suggested_object_id="phone"
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_NOTIFY_ENTITY: phone.id},
        subentries_data=[box_subentry(hass, box_one, 1, PLAYERS_ONE)],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await insert(hass, "04-99-99-99")
    assert len(services["persistent_notification.create"]) == 1


async def test_czech(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    hass.config.language = "cs"
    await insert(hass, "04-99-99-99")
    [note] = services["persistent_notification.create"]
    assert note.data["title"] == "Box 1: Neznámá karta"
