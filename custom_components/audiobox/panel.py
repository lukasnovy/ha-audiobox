"""The card pairing panel: sidebar entry, its module, websocket commands, covers."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import probatio

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.frontend import DATA_PANELS
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.loader import async_get_integration

from .cards import card_errors, card_from_subentry, find_card_subentry, normalize_uid
from .const import (
    CONF_MEDIA,
    CONF_SHUFFLE,
    CONF_UID,
    DOMAIN,
    SIGNAL_PANEL_UPDATE,
    SUBENTRY_CARD,
)
from .models import AudioboxConfigEntry, domain_data

PANEL_URL: Final = "audiobox"
STATIC_URL: Final = "/audiobox_static"
MODULE: Final = "audiobox-panel.js"
WEBCOMPONENT: Final = "audiobox-panel"


async def async_setup_panel_api(hass: HomeAssistant) -> None:
    """Serve the module and register the commands. Once per run, from `async_setup`."""
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                STATIC_URL, str(Path(__file__).parent / "frontend"), cache_headers=False
            )
        ]
    )
    websocket_api.async_register_command(hass, ws_subscribe)
    websocket_api.async_register_command(hass, ws_pair)
    websocket_api.async_register_command(hass, ws_unpair)


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


def _loaded_entry(hass: HomeAssistant) -> AudioboxConfigEntry | None:
    entries: list[AudioboxConfigEntry] = hass.config_entries.async_loaded_entries(
        DOMAIN
    )
    return entries[0] if entries else None


def _panel_state(hass: HomeAssistant) -> dict[str, Any]:
    """The cards and the last tap, as the panel gets them."""
    cards: list[dict[str, Any]] = []
    for entry in hass.config_entries.async_entries(DOMAIN)[:1]:
        for subentry in entry.get_subentries_of_type(SUBENTRY_CARD):
            card = card_from_subentry(subentry)
            cards.append({"uid": card.uid, "name": card.name, "media_id": card.media_id})
    tap = domain_data(hass).last_tap
    return {
        "cards": cards,
        "last_tap": None
        if tap is None
        else {"uid": tap.uid, "box": tap.box_name, "at": tap.at.isoformat()},
    }


@websocket_api.websocket_command({probatio.Required("type"): "audiobox/subscribe"})
@websocket_api.require_admin
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Send the cards and the last tap now and after every change (ADR-40)."""
    if _loaded_entry(hass) is None:
        connection.send_error(msg["id"], "not_loaded", "Audiobox is not loaded")
        return
    data = domain_data(hass)

    @callback
    def push() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], _panel_state(hass))
        )

    unsub = async_dispatcher_connect(hass, SIGNAL_PANEL_UPDATE, push)
    # ADR-42: an open panel mutes the unknown-card notification.
    data.panel_subscribers += 1

    @callback
    def unsubscribe() -> None:
        unsub()
        data.panel_subscribers -= 1

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    push()


def _player_for(hass: HomeAssistant, entry: AudioboxConfigEntry, uid: str) -> str | None:
    """A player for the stored media selector value; the form refuses one without.

    The first player of the box the card was tapped on, else of any box.
    """
    boxes = entry.runtime_data.boxes
    tap = domain_data(hass).last_tap
    tapped = boxes.get(tap.box_subentry_id) if tap and tap.uid == uid else None
    for controller in ([tapped] if tapped else []) + list(boxes.values()):
        if controller.config.players:
            return controller.config.players[0].entity_id
    return None


@websocket_api.websocket_command(
    {
        probatio.Required("type"): "audiobox/pair",
        probatio.Required("uid"): str,
        probatio.Required("uri"): str,
        probatio.Required("name"): str,
    }
)
@websocket_api.require_admin
@callback
def ws_pair(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Give a card a book: a new card, or a known card a different book."""
    if (entry := _loaded_entry(hass)) is None:
        connection.send_error(msg["id"], "not_loaded", "Audiobox is not loaded")
        return
    uid = normalize_uid(msg["uid"])
    uri: str = msg["uri"]
    name = msg["name"].strip() or uri
    existing = find_card_subentry(entry, uid)
    errors = card_errors(entry, uid, uri, uid if existing else None)
    if errors:
        code = errors.get(CONF_UID) or errors[CONF_MEDIA]
        connection.send_error(msg["id"], code, code)
        return

    # The shape the card form stores, so the form can edit a panel card.
    metadata: dict[str, Any] = {"title": name}
    if thumbnail := domain_data(hass).images.get(uri):
        metadata["thumbnail"] = thumbnail
    media: dict[str, Any] = {
        "media_content_id": uri,
        "media_content_type": "music",
        "metadata": metadata,
    }
    if player := _player_for(hass, entry, uid):
        media = {"entity_id": player, **media}

    if existing is not None:
        hass.config_entries.async_update_subentry(
            entry,
            existing,
            data={**existing.data, CONF_NAME: name, CONF_MEDIA: media},
            title=name,
        )
    else:
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data=MappingProxyType(
                    {CONF_UID: uid, CONF_NAME: name, CONF_MEDIA: media, CONF_SHUFFLE: False}
                ),
                subentry_type=SUBENTRY_CARD,
                title=name,
                unique_id=uid,
            ),
        )
    connection.send_result(msg["id"], {"uid": uid})


@websocket_api.websocket_command(
    {probatio.Required("type"): "audiobox/unpair", probatio.Required("uid"): str}
)
@websocket_api.require_admin
@callback
def ws_unpair(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Delete a card."""
    if (entry := _loaded_entry(hass)) is None:
        connection.send_error(msg["id"], "not_loaded", "Audiobox is not loaded")
        return
    if (subentry := find_card_subentry(entry, msg["uid"])) is None:
        connection.send_error(msg["id"], "not_found", "No card with this UID")
        return
    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    connection.send_result(msg["id"])
