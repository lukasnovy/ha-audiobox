"""Notifications, in the language of Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_NOTIFY_ENTITY
from .models import AudioboxConfigEntry, resolve_entity

_LOGGER = logging.getLogger(__name__)

MESSAGES: dict[str, dict[str, tuple[str, str]]] = {
    "en": {
        "unknown_card": (
            "Unknown card",
            "Card {uid} is not set up yet. Add it with Add card on the Audiobox"
            " page; the UID is already filled in.",
        ),
        "no_ma_user": (
            "Music Assistant user missing",
            "This box has no Music Assistant user, so nothing plays.",
        ),
        "battery_low": ("Battery low", "{level} % - time to charge it."),
        "offline": ("Offline", "The box dropped off the network."),
    },
    "cs": {
        "unknown_card": (
            "Neznámá karta",
            "Karta {uid} zatím není nastavená. Přidej ji přes Přidat kartu na"
            " stránce Audiobox, UID už tam bude vyplněné.",
        ),
        "no_ma_user": (
            "Chybí uživatel Music Assistant",
            "Krabička nemá uživatele Music Assistant, takže nic nehraje.",
        ),
        "battery_low": ("Slabá baterie", "{level} % - dej ji nabít."),
        "offline": ("Offline", "Krabička vypadla ze sítě."),
    },
}


async def async_notify(
    hass: HomeAssistant,
    entry: AudioboxConfigEntry,
    box_name: str,
    key: str,
    **params: Any,
) -> None:
    """Send a notification about a box, titled with its name."""
    texts = MESSAGES.get(hass.config.language.split("-")[0], MESSAGES["en"])
    title, message = texts[key]
    title = f"{box_name}: {title}"
    message = message.format(**params)

    if entity_id := resolve_entity(hass, entry.data.get(CONF_NOTIFY_ENTITY)):
        try:
            await hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": entity_id, "title": title, "message": message},
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "Notification to %s failed, falling back: %s", entity_id, err
            )
        else:
            return
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {"title": title, "message": message},
        blocking=True,
    )
