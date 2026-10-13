"""Tests for the Audiobox entry flow."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.audiobox.const import CONF_NOTIFY_ENTITY, DOMAIN

from .common import suggested

pytestmark = pytest.mark.usefixtures("mqtt_mock", "skip_setup")


@pytest.fixture
def skip_setup() -> Generator[None]:
    """Do not set the entry up after the flow creates it."""
    with patch("custom_components.audiobox.async_setup_entry", return_value=True):
        yield


async def test_create_without_target(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Audiobox"
    assert result["data"] == {CONF_NOTIFY_ENTITY: None}


async def test_target_stored_as_registry_id(hass: HomeAssistant) -> None:
    phone = er.async_get(hass).async_get_or_create(
        "notify", "test", "phone", suggested_object_id="phone"
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NOTIFY_ENTITY: "notify.phone"}
    )
    assert result["data"] == {CONF_NOTIFY_ENTITY: phone.id}


async def test_single_instance(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_reconfigure_changes_target(hass: HomeAssistant) -> None:
    ent_reg = er.async_get(hass)
    phone = ent_reg.async_get_or_create(
        "notify", "test", "phone", suggested_object_id="phone"
    )
    tablet = ent_reg.async_get_or_create(
        "notify", "test", "tablet", suggested_object_id="tablet"
    )
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_NOTIFY_ENTITY: phone.id})
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    assert suggested(result, CONF_NOTIFY_ENTITY) == "notify.phone"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NOTIFY_ENTITY: "notify.tablet"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == {CONF_NOTIFY_ENTITY: tablet.id}
