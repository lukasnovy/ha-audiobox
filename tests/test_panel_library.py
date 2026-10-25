"""The Music Assistant library for the pairing panel, and the cover proxy."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch

import pytest
from yarl import URL

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    MockHAClientWebSocket,
    WebSocketGenerator,
)

from custom_components.audiobox.cards import find_card_subentry
from custom_components.audiobox.const import CONF_MEDIA
from custom_components.audiobox.panel import cover_url

MA = "http://music-assistant:8095"
BOOKS = [
    {
        "media_type": "audiobook",
        "uri": f"library://audiobook/{number}",
        "name": f"Book {number:04}",
        "version": "",
        "image": None
        if number == 0
        else f"{MA}/imageproxy?path=cover{number}&provider=abs&size=0",
    }
    for number in range(1001)
]


class Library:
    """A stand-in `music_assistant.get_library`."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error: Exception | None = None

    def handler(self, call: ServiceCall) -> ServiceResponse:
        self.calls.append(dict(call.data))
        if self.error is not None:
            raise self.error
        offset, limit = call.data["offset"], call.data["limit"]
        return {"items": BOOKS[offset : offset + limit], "offset": offset, "limit": limit}


@pytest.fixture
def library(hass: HomeAssistant) -> Generator[Library]:
    """A loaded Music Assistant entry and its library action."""
    entry = MockConfigEntry(domain="music_assistant", state=ConfigEntryState.LOADED)
    entry.add_to_hass(hass)
    library = Library()
    hass.services.async_register(
        "music_assistant",
        "get_library",
        library.handler,
        supports_response=SupportsResponse.ONLY,
    )
    yield library
    # Unloading a "loaded" entry at teardown would import the real integration.
    entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


async def _load(
    client: MockHAClientWebSocket, media_type: str = "audiobook"
) -> dict[str, Any]:
    await client.send_json_auto_id({"type": "audiobox/library", "media_type": media_type})
    return await client.receive_json()


@pytest.fixture
async def items(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    library: Library,
    hass_ws_client: WebSocketGenerator,
) -> list[dict[str, Any]]:
    """The audiobooks as the panel receives them."""
    result = await _load(await hass_ws_client(hass))
    assert result["success"], result
    return result["result"]["items"]


def test_cover_url() -> None:
    url = URL(cover_url(f"{MA}/imageproxy?path=x&size=0"))
    assert url.query.getall("size") == ["128"]
    assert url.query["path"] == "x"
    assert cover_url("https://cdn.example/a.jpg") == "https://cdn.example/a.jpg"


async def test_library_pages(items: list[dict[str, Any]], library: Library) -> None:
    assert [call["offset"] for call in library.calls] == [0, 500, 1000]
    assert {call["limit"] for call in library.calls} == {500}
    assert {call["media_type"] for call in library.calls} == {"audiobook"}
    assert [item["uri"] for item in items] == [book["uri"] for book in BOOKS]
    assert items[1]["name"] == "Book 0001"
    assert items[0]["image"] is None
    assert items[1]["image"].startswith("/api/audiobox/cover/")
    assert "authSig=" in items[1]["image"]


async def test_library_without_music_assistant(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    result = await _load(await hass_ws_client(hass))
    assert not result["success"]
    assert result["error"]["code"] == "music_assistant_not_loaded"


async def test_library_error(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    library: Library,
    hass_ws_client: WebSocketGenerator,
) -> None:
    library.error = HomeAssistantError("boom")
    result = await _load(await hass_ws_client(hass))
    assert not result["success"]
    assert result["error"]["code"] == "library_failed"
    assert result["error"]["message"] == "boom"


async def test_cover_proxy(
    items: list[dict[str, Any]],
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{MA}/imageproxy?path=cover1&provider=abs&size=128",
        content=b"jpeg bytes",
        headers={"Content-Type": "image/jpeg"},
    )
    response = await (await hass_client()).get(items[1]["image"])
    assert response.status == 200
    assert await response.read() == b"jpeg bytes"
    assert response.headers["Content-Type"] == "image/jpeg"
    assert response.headers["Cache-Control"] == "private, max-age=86400"
    assert aioclient_mock.call_count == 1


async def test_cover_unknown_key(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_client: ClientSessionGenerator
) -> None:
    response = await (await hass_client()).get("/api/audiobox/cover/0123456789abcdef")
    assert response.status == 404


async def test_cover_upstream_error(
    items: list[dict[str, Any]],
    hass_client: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(f"{MA}/imageproxy?path=cover1&provider=abs&size=128", status=500)
    response = await (await hass_client()).get(items[1]["image"])
    assert response.status == 502


async def test_cover_needs_auth(
    items: list[dict[str, Any]],
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{MA}/imageproxy?path=cover1&provider=abs&size=128",
        content=b"jpeg bytes",
        headers={"Content-Type": "image/jpeg"},
    )
    client = await hass_client_no_auth()
    # A refused request makes Home Assistant look up the caller's host name.
    with patch(
        "homeassistant.components.http.ban.gethostbyaddr",
        return_value=("localhost", [], []),
    ):
        async with client.get(URL(items[1]["image"]).path) as response:
            assert response.status == 401
    async with client.get(items[1]["image"]) as response:
        assert response.status == 200


async def test_pair_stores_thumbnail(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    items: list[dict[str, Any]],
    hass_ws_client: WebSocketGenerator,
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "audiobox/pair",
            "uid": "aa-bb-cc-dd",
            "uri": "library://audiobook/1",
            "name": "Book 0001",
        }
    )
    assert (await client.receive_json())["success"]
    subentry = find_card_subentry(loaded, "aa-bb-cc-dd")
    assert subentry is not None
    assert subentry.data[CONF_MEDIA]["metadata"]["thumbnail"] == BOOKS[1]["image"]
