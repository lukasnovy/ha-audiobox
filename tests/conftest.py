"""Fixtures for the Audiobox tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiobox.const import CONF_NOTIFY_ENTITY, DOMAIN

from .common import (
    BOOK_UID,
    BOOK_URI,
    PLAYERS_ONE,
    PLAYLIST_UID,
    PLAYLIST_URI,
    Services,
    box_subentry,
    card_subentry,
    register_box_device,
    register_player,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load integrations from custom_components."""


@pytest.fixture
async def mqtt_mock(hass: HomeAssistant, mqtt_mock: Any) -> AsyncGenerator[Any]:
    """MQTT, without the housekeeping timer the mock client leaves behind.

    Home Assistant core exempts its own integration tests from the lingering
    timer check; custom integrations are not exempt. Only MQTT's timer is
    cancelled here, so a timer of ours left running still fails the test.
    """
    yield mqtt_mock
    client = hass.data["mqtt"].client
    if client._misc_timer is not None:
        client._misc_timer.cancel()
        client._misc_timer = None


@pytest.fixture(autouse=True)
def no_settle() -> Generator[None]:
    """Skip the one-second pause before a new book."""
    with patch("custom_components.audiobox.const.SETTLE_SECONDS", 0):
        yield


@pytest.fixture
def box_one(hass: HomeAssistant) -> dr.DeviceEntry:
    """Box 1 as MQTT discovery registers it."""
    return register_box_device(hass, 1)


@pytest.fixture
def players(hass: HomeAssistant) -> list[str]:
    """The box's own player and two room speakers."""
    return [
        register_player(hass, "audiobox_1"),
        register_player(hass, "kids_room"),
        register_player(hass, "living_room"),
    ]


@pytest.fixture
def services(hass: HomeAssistant) -> Services:
    """Mock every action the integration calls."""
    return Services(hass)


@pytest.fixture
def entry(
    hass: HomeAssistant, box_one: dr.DeviceEntry, players: list[str]
) -> MockConfigEntry:
    """An entry with box 1, a book card and a shuffled playlist card."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Audiobox",
        data={CONF_NOTIFY_ENTITY: None},
        subentries_data=[
            box_subentry(hass, box_one, 1, PLAYERS_ONE),
            card_subentry(BOOK_UID, BOOK_URI, "Book"),
            card_subentry(PLAYLIST_UID, PLAYLIST_URI, "Songs", shuffle=True),
        ],
    )


@pytest.fixture
async def loaded(
    hass: HomeAssistant, mqtt_mock: None, entry: MockConfigEntry, services: Services
) -> MockConfigEntry:
    """The entry, set up."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
