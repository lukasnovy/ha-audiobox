"""Runtime data and entity helpers for the Audiobox integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


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
