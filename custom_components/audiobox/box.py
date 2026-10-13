"""One box: listens to its entities and buttons, drives Music Assistant."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime
import logging
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
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
from .models import AudioboxConfigEntry, BoxConfig

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
