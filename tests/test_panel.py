"""The pairing panel in the sidebar and its module."""

from homeassistant.components.frontend import DATA_PANELS
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .common import settle


async def test_panel_registered(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    panel = hass.data[DATA_PANELS]["audiobox"]
    assert panel.require_admin
    assert panel.sidebar_title == "Audiobox"
    custom = panel.config["_panel_custom"]
    assert custom["name"] == "audiobox-panel"
    assert custom["module_url"] == "/audiobox_static/audiobox-panel.js?v=0.2.0"


async def test_panel_survives_reload(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    assert await hass.config_entries.async_reload(loaded.entry_id)
    await settle(hass)
    assert "audiobox" in hass.data[DATA_PANELS]


async def test_panel_removed_with_entry(
    hass: HomeAssistant, loaded: MockConfigEntry
) -> None:
    await hass.config_entries.async_remove(loaded.entry_id)
    await settle(hass)
    assert "audiobox" not in hass.data[DATA_PANELS]


async def test_module_served(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_client: ClientSessionGenerator
) -> None:
    client = await hass_client()
    response = await client.get("/audiobox_static/audiobox-panel.js")
    assert response.status == 200
    assert 'customElements.define("audiobox-panel"' in await response.text()
