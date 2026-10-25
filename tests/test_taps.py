"""Taps for the pairing panel, and the unknown-card mute while it is open."""

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiobox.const import SIGNAL_PANEL_UPDATE, SUBENTRY_BOX
from custom_components.audiobox.models import domain_data

from .common import BOOK_UID, RED, Services, insert, remove, settle


def _box_subentry_id(entry: MockConfigEntry) -> str:
    return next(iter(entry.get_subentries_of_type(SUBENTRY_BOX))).subentry_id


async def test_unknown_tap_recorded(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    await insert(hass, "AA-BB-CC-DD")
    tap = domain_data(hass).last_tap
    assert tap is not None
    assert tap.uid == "aa-bb-cc-dd"
    assert tap.box_name == "Box 1"
    assert tap.box_subentry_id == _box_subentry_id(loaded)


async def test_known_tap_recorded(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    await insert(hass, BOOK_UID)
    tap = domain_data(hass).last_tap
    assert tap is not None
    assert tap.uid == BOOK_UID
    assert len(services["music_assistant.play_media"]) == 1


async def test_tap_signal(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    calls: list[None] = []

    @callback
    def listener() -> None:
        calls.append(None)

    async_dispatcher_connect(hass, SIGNAL_PANEL_UPDATE, listener)
    await insert(hass, "aa-bb-cc-dd")
    assert len(calls) == 1


async def test_tap_survives_reload(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    await insert(hass, "aa-bb-cc-dd")
    tap = domain_data(hass).last_tap
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await settle(hass)
    assert domain_data(hass).last_tap == tap


async def test_unknown_card_muted_while_panel_open(
    hass: HomeAssistant, loaded: MockConfigEntry, services: Services
) -> None:
    domain_data(hass).panel_subscribers = 1
    await insert(hass, "aa-bb-cc-dd")
    assert services.led_colours()[-1] == RED
    assert services["notify.send_message"] == []
    assert services["persistent_notification.create"] == []

    domain_data(hass).panel_subscribers = 0
    await remove(hass)
    await insert(hass, "aa-bb-cc-ee")
    assert len(services["persistent_notification.create"]) == 1
