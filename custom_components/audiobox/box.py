"""One box: listens to its entities and buttons, drives Music Assistant."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime
from functools import partial
import logging
from typing import Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from . import const
from .cards import find_card, normalize_uid
from .models import AudioboxConfigEntry, BoxConfig
from .notifications import async_notify

_LOGGER = logging.getLogger(__name__)

MEDIA_PLAYER = "media_player"
MUSIC_ASSISTANT = "music_assistant"
LIGHT = "light"
NOT_READY = (STATE_UNAVAILABLE, STATE_UNKNOWN)


class BoxController:
    """The brain of one box."""

    def __init__(
        self, hass: HomeAssistant, entry: AudioboxConfigEntry, config: BoxConfig
    ) -> None:
        """Start with the box's own player selected and no card."""
        self.hass = hass
        self.entry = entry
        self.config = config
        self._lock = asyncio.Lock()
        self._selected = config.players[0].entity_id if config.players else ""
        self._last_card = const.NO_CARD
        self._listeners: list[CALLBACK_TYPE] = []
        self._unsubs: list[CALLBACK_TYPE] = []
        self._session_timer: CALLBACK_TYPE | None = None
        self._battery_timer: CALLBACK_TYPE | None = None
        self._led_off: CALLBACK_TYPE | None = None
        self._volume_task: asyncio.Task[None] | None = None

    # --- selection ---------------------------------------------------------

    @property
    def selected_player(self) -> str:
        """Entity ID of the selected player."""
        return self._selected

    @property
    def selected_player_name(self) -> str | None:
        """Name of the selected player, as the select entity shows it."""
        for player in self.config.players:
            if player.entity_id == self._selected:
                return player.name
        return None

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Call `listener` whenever the selection changes."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def restore_selection(self, name: str) -> None:
        """Restore a selection after a restart. Unknown names are ignored."""
        for player in self.config.players:
            if player.name == name:
                self._selected = player.entity_id
                return

    @callback
    def select_player_by_name(self, name: str) -> None:
        """Select a player by hand. Playback does not move (ADR-33)."""
        for player in self.config.players:
            if player.name == name:
                self._set_selection(player.entity_id)
                return

    @callback
    def _set_selection(self, entity_id: str) -> None:
        self._selected = entity_id
        for listener in list(self._listeners):
            listener()

    # --- lifecycle ---------------------------------------------------------

    async def async_start(self) -> None:
        """Start listening."""
        if self.config.card_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.config.card_entity], self._card_changed
                )
            )

    @callback
    def async_stop(self) -> None:
        """Stop listening and cancel timers."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for timer in (self._session_timer, self._battery_timer, self._led_off):
            if timer is not None:
                timer()
        self._session_timer = self._battery_timer = self._led_off = None

    # --- plumbing ----------------------------------------------------------

    @callback
    def _schedule(
        self, job: Callable[[], Coroutine[Any, Any, None]], name: str
    ) -> None:
        """Run `job` after this box's earlier jobs, without blocking the caller."""
        self.entry.async_create_background_task(
            self.hass,
            self._run_locked(job, name),
            f"audiobox {self.config.name} {name}",
        )

    async def _run_locked(
        self, job: Callable[[], Coroutine[Any, Any, None]], name: str
    ) -> None:
        async with self._lock:
            try:
                await job()
            except HomeAssistantError as err:
                _LOGGER.warning("%s: %s failed: %s", self.config.name, name, err)

    async def _async_call(
        self, domain: str, service: str, data: dict[str, Any], *, blocking: bool = True
    ) -> None:
        await self.hass.services.async_call(domain, service, data, blocking=blocking)

    async def _async_try_call(
        self, domain: str, service: str, data: dict[str, Any], *, blocking: bool = True
    ) -> None:
        """Call an action; log a failure instead of raising it."""
        try:
            await self._async_call(domain, service, data, blocking=blocking)
        except HomeAssistantError as err:
            _LOGGER.warning(
                "%s: %s.%s failed: %s", self.config.name, domain, service, err
            )

    def _available(self, entity_id: str | None) -> bool:
        if not entity_id:
            return False
        state = self.hass.states.get(entity_id)
        return state is not None and state.state not in NOT_READY

    def _is(self, entity_id: str | None, value: str) -> bool:
        return bool(entity_id) and self.hass.states.is_state(entity_id, value)

    async def _async_wait_for(
        self, entity_id: str, wanted: str, timeout: float
    ) -> bool:
        """Wait until `entity_id` is `wanted`. False after `timeout` seconds."""
        if self._is(entity_id, wanted):
            return True
        done: asyncio.Future[bool] = self.hass.loop.create_future()

        @callback
        def changed(event: Event[EventStateChangedData]) -> None:
            new = event.data["new_state"]
            if new is not None and new.state == wanted and not done.done():
                done.set_result(True)

        unsub = async_track_state_change_event(self.hass, [entity_id], changed)
        try:
            async with asyncio.timeout(timeout):
                return await done
        except TimeoutError:
            return False
        finally:
            unsub()

    # --- LED -----------------------------------------------------------------

    async def _async_flash(self, colour: str, seconds: float) -> None:
        """Light the LED, then turn it off. A new flash replaces a running one."""
        led = self.config.led_entity
        if not led:
            return
        self._cancel_led_off()
        await self._async_try_call(
            LIGHT,
            "turn_on",
            {
                ATTR_ENTITY_ID: led,
                "rgb_color": list(const.COLOURS[colour]),
                "brightness": const.LED_BRIGHTNESS,
            },
            blocking=False,
        )
        self._led_off = async_call_later(self.hass, seconds, self._led_off_fired)

    @callback
    def _led_off_fired(self, _now: datetime) -> None:
        self._led_off = None
        self.hass.async_create_task(self._async_led_off())

    async def _async_led_off(self) -> None:
        self._cancel_led_off()
        if self.config.led_entity:
            await self._async_try_call(
                LIGHT,
                "turn_off",
                {ATTR_ENTITY_ID: self.config.led_entity},
                blocking=False,
            )

    @callback
    def _cancel_led_off(self) -> None:
        if self._led_off is not None:
            self._led_off()
            self._led_off = None

    # --- notifications and timers --------------------------------------------

    @callback
    def _notify(self, key: str, **params: Any) -> None:
        self.entry.async_create_background_task(
            self.hass,
            async_notify(self.hass, self.entry, self.config.name, key, **params),
            f"audiobox {self.config.name} notify {key}",
        )

    @callback
    def _cancel_session_timer(self) -> None:
        if self._session_timer is not None:
            self._session_timer()
            self._session_timer = None

    # --- card ----------------------------------------------------------------

    @callback
    def _card_changed(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        old = event.data["old_state"]
        if new is None:
            return
        old_state = old.state if old is not None else None
        if new.state in (*NOT_READY, "") or new.state == old_state:
            return
        if new.state == const.NO_CARD:
            self._schedule(self._async_card_out, "card out")
            return
        uid = normalize_uid(new.state)
        self._cancel_session_timer()
        self._schedule(partial(self._async_play_card, uid), "play card")

    async def _async_play_card(self, uid: str) -> None:
        """2026-10-11 spec section 7 `audiobox_play_card`, step for step."""
        self._cancel_session_timer()
        config = self.config
        player = self._selected

        # ADR-25: without a user the position would go into every child's account.
        if not config.ma_user:
            await self._async_flash("red", 3)
            self._notify("no_ma_user")
            return

        card = find_card(self.entry, uid)
        if card is None:
            self.entry.runtime_data.last_unknown_uid = uid
            await self._async_flash("red", 3)
            self._notify("unknown_card", uid=uid)
            return

        if not self._available(player):
            await self._async_flash("amber", 3)
            return

        # Fast path: same card, queue still loaded and paused.
        if uid == self._last_card and self._is(player, STATE_PAUSED):
            await self._async_call(MEDIA_PLAYER, "media_play", {ATTR_ENTITY_ID: player})
            await self._async_flash("green", 1)
            return

        if self._is(player, STATE_PLAYING):
            await self._async_call(MEDIA_PLAYER, "media_pause", {ATTR_ENTITY_ID: player})
            await asyncio.sleep(const.SETTLE_SECONDS)

        try:
            await self._async_call(
                MUSIC_ASSISTANT,
                "play_media",
                {
                    ATTR_ENTITY_ID: player,
                    "media_id": card.media_id,
                    "enqueue": "replace",
                    "username": config.ma_user,
                },
            )
        except HomeAssistantError as err:
            _LOGGER.warning("%s: playing %s failed: %s", config.name, card.name, err)
            await self._async_flash("red", 3)
            return

        if not await self._async_wait_for(
            player, STATE_PLAYING, const.PLAY_CONFIRM_SECONDS
        ):
            await self._async_flash("red", 3)
            return

        if card.media_type == const.MEDIA_TYPE_PLAYLIST and card.shuffle:
            await self._async_try_call(
                MEDIA_PLAYER, "shuffle_set", {ATTR_ENTITY_ID: player, "shuffle": True}
            )
        self._last_card = uid
        await self._async_flash("green", 1)

    # --- card out and the end of a session ------------------------------------

    def _card_in_tray(self) -> bool:
        if self.config.card_present_entity:
            return self._is(self.config.card_present_entity, STATE_ON)
        state = (
            self.hass.states.get(self.config.card_entity)
            if self.config.card_entity
            else None
        )
        return state is not None and state.state not in (*NOT_READY, const.NO_CARD, "")

    async def _async_card_out(self) -> None:
        """Pause, not stop: re-inserting the same card resumes instantly (ADR-5)."""
        player = self._selected
        if self._is(player, STATE_PLAYING):
            await self._async_try_call(
                MEDIA_PLAYER, "media_pause", {ATTR_ENTITY_ID: player}
            )
        await self._async_led_off()
        self._cancel_session_timer()
        self._session_timer = async_call_later(
            self.hass, const.SESSION_END, self._session_end_fired
        )

    @callback
    def _session_end_fired(self, _now: datetime) -> None:
        self._session_timer = None
        self._schedule(self._async_end_session, "end session")

    async def _async_end_session(self) -> None:
        """Stop, which flushes progress, and hand the selection back (ADR-17)."""
        if self._card_in_tray():
            return
        player = self._selected
        if self._available(player):
            await self._async_try_call(
                MEDIA_PLAYER, "media_stop", {ATTR_ENTITY_ID: player}
            )
        self._last_card = const.NO_CARD
        if self.config.players:
            self._set_selection(self.config.players[0].entity_id)
