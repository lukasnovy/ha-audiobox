"""The card pairing panel: sidebar entry, its module, websocket commands, covers."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.loader import async_get_integration

from .const import DOMAIN
from .models import domain_data

PANEL_URL: Final = "audiobox"
STATIC_URL: Final = "/audiobox_static"
MODULE: Final = "audiobox-panel.js"
WEBCOMPONENT: Final = "audiobox-panel"


async def async_setup_panel_api(hass: HomeAssistant) -> None:
    """Serve the module. Once per run: static routes cannot be removed."""
    data = domain_data(hass)
    if data.static_registered:
        return
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STATIC_URL, str(Path(__file__).parent / "frontend"), cache_headers=False
            )
        ]
    )
    data.static_registered = True


async def async_register_panel(hass: HomeAssistant) -> None:
    """Add the sidebar entry, unless a reload left it in place (ADR-36)."""
    if PANEL_URL in hass.data.get(DATA_PANELS, {}):
        return
    version = (await async_get_integration(hass, DOMAIN)).version
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=WEBCOMPONENT,
        sidebar_title="Audiobox",
        sidebar_icon="mdi:card-account-details-outline",
        module_url=f"{STATIC_URL}/{MODULE}?v={version}",
        require_admin=True,
    )


@callback
def async_remove_panel(hass: HomeAssistant) -> None:
    """Remove the sidebar entry."""
    frontend.async_remove_panel(hass, PANEL_URL, warn_if_unknown=False)
