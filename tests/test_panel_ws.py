"""Websocket commands of the pairing panel: subscribe, pair, unpair."""

from typing import Any

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    MockHAClientWebSocket,
    WebSocketGenerator,
)

from custom_components.audiobox.cards import find_card, find_card_subentry
from custom_components.audiobox.const import CONF_MEDIA, CONF_SHUFFLE, SUBENTRY_CARD
from custom_components.audiobox.models import domain_data

from .common import (
    BOOK_UID,
    BOX_PLAYER,
    PLAYLIST_UID,
    Services,
    insert,
    remove,
    settle,
)

NEW_UID = "aa-bb-cc-dd"


async def _command(client: MockHAClientWebSocket, **message: Any) -> dict[str, Any]:
    await client.send_json_auto_id(message)
    return await client.receive_json()


async def _subscribe(client: MockHAClientWebSocket) -> tuple[int, dict[str, Any]]:
    result = await _command(client, type="audiobox/subscribe")
    assert result["success"], result
    event = await client.receive_json()
    return result["id"], event["event"]


def _uids(state: dict[str, Any]) -> set[str]:
    return {card["uid"] for card in state["cards"]}


def _card_count(entry: MockConfigEntry) -> int:
    return len(entry.get_subentries_of_type(SUBENTRY_CARD))


async def test_subscribe_initial_state(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    await insert(hass, NEW_UID)
    _, state = await _subscribe(await hass_ws_client(hass))
    assert _uids(state) == {BOOK_UID, PLAYLIST_UID}
    book = next(card for card in state["cards"] if card["uid"] == BOOK_UID)
    assert book["name"] == "Book"
    assert book["media_id"] == "library://audiobook/12345"
    assert state["last_tap"]["uid"] == NEW_UID
    assert state["last_tap"]["box"] == "Box 1"
    assert state["last_tap"]["at"]


async def test_subscribe_pushes_tap_and_card_changes(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    client = await hass_ws_client(hass)
    _, state = await _subscribe(client)
    assert state["last_tap"] is None

    await insert(hass, NEW_UID)
    event = await client.receive_json()
    assert event["event"]["last_tap"]["uid"] == NEW_UID

    subentry = find_card_subentry(loaded, BOOK_UID)
    assert subentry is not None
    hass.config_entries.async_remove_subentry(loaded, subentry.subentry_id)
    await settle(hass)
    event = await client.receive_json()
    assert _uids(event["event"]) == {PLAYLIST_UID}


async def test_pair_new_card_plays(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    services: Services,
    hass_ws_client: WebSocketGenerator,
) -> None:
    await insert(hass, NEW_UID.upper())
    client = await hass_ws_client(hass)
    result = await _command(
        client,
        type="audiobox/pair",
        uid=NEW_UID.upper(),
        uri="library://audiobook/77",
        name="New",
    )
    assert result["success"], result
    assert result["result"] == {"uid": NEW_UID}

    card = find_card(loaded, NEW_UID)
    assert card is not None
    assert card.media_id == "library://audiobook/77"
    subentry = find_card_subentry(loaded, NEW_UID)
    assert subentry is not None
    assert subentry.title == "New"
    assert subentry.unique_id == NEW_UID
    assert subentry.data[CONF_MEDIA]["entity_id"] == BOX_PLAYER
    assert subentry.data[CONF_MEDIA]["media_content_type"] == "music"
    assert subentry.data[CONF_MEDIA]["metadata"]["title"] == "New"
    assert subentry.data[CONF_SHUFFLE] is False

    await remove(hass)
    await insert(hass, NEW_UID)
    assert [c.data["media_id"] for c in services["music_assistant.play_media"]] == [
        "library://audiobook/77"
    ]


async def test_pair_reassigns_and_keeps_shuffle(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    result = await _command(
        await hass_ws_client(hass),
        type="audiobox/pair",
        uid=PLAYLIST_UID,
        uri="library://playlist/8",
        name="Other",
    )
    assert result["success"], result
    assert _card_count(loaded) == 2
    subentry = find_card_subentry(loaded, PLAYLIST_UID)
    assert subentry is not None
    assert subentry.data[CONF_SHUFFLE] is True
    assert subentry.data["name"] == "Other"
    assert subentry.title == "Other"
    assert subentry.data[CONF_MEDIA]["media_content_id"] == "library://playlist/8"


async def test_pair_refused(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    client = await hass_ws_client(hass)
    for uid, uri, code in (
        ("04-aa", "library://audiobook/1", "invalid_uid"),
        (NEW_UID, "library://album/1", "unsupported_media"),
        (NEW_UID, "spotify://audiobook/1", "not_library_audiobook"),
    ):
        result = await _command(client, type="audiobox/pair", uid=uid, uri=uri, name="X")
        assert not result["success"]
        assert result["error"]["code"] == code
    assert _card_count(loaded) == 2


async def test_unpair(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    client = await hass_ws_client(hass)
    result = await _command(client, type="audiobox/unpair", uid=BOOK_UID.upper())
    assert result["success"], result
    assert find_card(loaded, BOOK_UID) is None

    result = await _command(client, type="audiobox/unpair", uid=BOOK_UID)
    assert not result["success"]
    assert result["error"]["code"] == "not_found"


async def test_subscriber_count(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    client = await hass_ws_client(hass)
    subscription, _ = await _subscribe(client)
    assert domain_data(hass).panel_subscribers == 1

    result = await _command(
        client, type="unsubscribe_events", subscription=subscription
    )
    assert result["success"], result
    assert domain_data(hass).panel_subscribers == 0


async def test_not_loaded(
    hass: HomeAssistant, loaded: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    assert await hass.config_entries.async_unload(loaded.entry_id)
    result = await _command(
        await hass_ws_client(hass),
        type="audiobox/pair",
        uid=NEW_UID,
        uri="library://audiobook/1",
        name="X",
    )
    assert not result["success"]
    assert result["error"]["code"] == "not_loaded"


async def test_admin_only(
    hass: HomeAssistant,
    loaded: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    client = await hass_ws_client(hass, hass_read_only_access_token)
    for message in (
        {"type": "audiobox/subscribe"},
        {"type": "audiobox/pair", "uid": NEW_UID, "uri": "library://audiobook/1", "name": "X"},
        {"type": "audiobox/unpair", "uid": BOOK_UID},
    ):
        result = await _command(client, **message)
        assert not result["success"]
        assert result["error"]["code"] == "unauthorized"
    assert _card_count(loaded) == 2
