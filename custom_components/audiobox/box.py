"""One box: listens to its entities and buttons, drives Music Assistant."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime
from functools import partial
import json
import logging
from typing import Any

from homeassistant.components import mqtt

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
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from . import const
from .cards import Card, find_card, normalize_uid
from .models import AudioboxConfigEntry, BoxConfig, Tap, domain_data
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
        self._battery_notified = False
        self._led_off: CALLBACK_TYPE | None = None
        self._volume_task: asyncio.Task[None] | None = None
        # Runs while the knob is being turned: the player's late reports of
        # earlier levels must not pull the knob back.
        self._knob_quiet: CALLBACK_TYPE | None = None
        # The choices payload last sent to the box, so it is sent only on a change.
        self._shown_choices: str | None = None
        # Set from a back/fwd/back_restart press until its seek has ended (ADR-44).
        self._seek_busy = False
        # Frees the seek buttons when the red no-card blink is over.
        self._seek_free: CALLBACK_TYPE | None = None
        # Runs for PAUSE_HOLD after playback was paused without a card: the
        # box's controls keep working meanwhile.
        self._pause_hold: CALLBACK_TYPE | None = None
        # The card went while the selected player played: its coming pause is
        # the card-out pause, which holds nothing.
        self._card_out_pause = False
        # The playing payload last sent to the box.
        self._shown_playing: str | None = None

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
                self._show_selected()
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
        # A knob turned for the previous player says nothing about this one.
        self._cancel_knob_quiet()
        for listener in list(self._listeners):
            listener()
        self._show_selected()
        self._show_playing()

    # --- lifecycle ---------------------------------------------------------

    async def async_start(self) -> None:
        """Start listening."""
        if self.config.card_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.config.card_entity], self._card_changed
                )
            )
        if self.config.volume_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.config.volume_entity], self._volume_changed
                )
            )
        if self.config.battery_entity:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.config.battery_entity], self._battery_changed
                )
            )
        if self.config.players:
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    [player.entity_id for player in self.config.players],
                    self._player_changed,
                )
            )
        self._unsubs.append(
            await mqtt.async_subscribe(
                self.hass,
                const.BUTTON_TOPIC.format(prefix=self.config.mqtt_prefix),
                self._button_received,
                qos=1,
            )
        )
        self._show_selected()
        self._show_playing()

    @callback
    def async_stop(self) -> None:
        """Stop listening and cancel timers."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for timer in (
            self._session_timer,
            self._battery_timer,
            self._led_off,
            self._seek_free,
            self._pause_hold,
        ):
            if timer is not None:
                timer()
        self._session_timer = self._battery_timer = self._led_off = None
        self._seek_free = self._pause_hold = None
        self._cancel_knob_quiet()

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
        if new.state == STATE_UNAVAILABLE:
            # ADR-35: only a box that was there goes offline. A fresh entity
            # after a Home Assistant start is not news.
            # A broker restart makes every MQTT entity unavailable too; that is
            # not the box going away.
            if old_state not in (None, *NOT_READY) and mqtt.is_connected(self.hass):
                self._notify("offline")
            return
        if new.state in (STATE_UNKNOWN, "") or new.state == old_state:
            return
        if new.state == const.NO_CARD:
            self._schedule(self._async_card_out, "card out")
            return
        uid = normalize_uid(new.state)
        domain_data(self.hass).last_tap = Tap(
            uid, self.config.subentry_id, self.config.name, dt_util.utcnow()
        )
        async_dispatcher_send(self.hass, const.SIGNAL_PANEL_UPDATE)
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
            # ADR-42: while cards are being paired, the red flash is enough.
            if domain_data(self.hass).panel_subscribers == 0:
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

        if card.media_type == const.MEDIA_TYPE_PLAYLIST:
            # Music Assistant keeps shuffle per queue, so "off" has to be said too.
            await self._async_try_call(
                MEDIA_PLAYER,
                "shuffle_set",
                {ATTR_ENTITY_ID: player, "shuffle": card.shuffle},
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
        self._cancel_pause_hold()
        playing = self._is(player, STATE_PLAYING)
        # The box's controls stop now, not when Music Assistant reports the
        # pause, and this pause holds nothing.
        self._card_out_pause = playing
        self._show_playing()
        if playing:
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

    # --- playback without a card ---------------------------------------------

    def _controls_active(self) -> bool:
        """The box's buttons and knob work: a card in the tray, or playback."""
        return self._card_in_tray() or self._playing()

    def _playing(self) -> bool:
        """The selected player plays, or was paused without a card lately.

        Playback started from the Music Assistant app counts as much as a card
        (2026-10-30).
        """
        if self._card_out_pause:
            return False
        return self._is(self._selected, STATE_PLAYING) or (
            self._pause_hold is not None and self._is(self._selected, STATE_PAUSED)
        )

    @callback
    def _playback_changed(self, old: State | None, new: State) -> None:
        """The selected player's state changed: start or end the pause hold."""
        old_state = old.state if old is not None else None
        if new.state == STATE_PLAYING:
            if old_state != STATE_PLAYING:
                self._card_out_pause = False
            self._cancel_pause_hold()
        elif new.state == STATE_PAUSED:
            if old_state == STATE_PLAYING:
                if self._card_out_pause:
                    self._card_out_pause = False
                elif not self._card_in_tray():
                    self._cancel_pause_hold()
                    self._pause_hold = async_call_later(
                        self.hass, const.PAUSE_HOLD, self._pause_hold_over
                    )
        else:
            # Stopped, off or gone: nothing left to hold.
            self._card_out_pause = False
            self._cancel_pause_hold()
        self._show_playing()

    @callback
    def _pause_hold_over(self, _now: datetime) -> None:
        self._pause_hold = None
        self._show_playing()

    @callback
    def _cancel_pause_hold(self) -> None:
        if self._pause_hold is not None:
            self._pause_hold()
            self._pause_hold = None

    @callback
    def _show_playing(self) -> None:
        """Tell the box whether playback keeps its controls on, when that changed."""
        payload = "ON" if self._playing() else "OFF"
        if payload == self._shown_playing:
            return
        self._shown_playing = payload
        self.entry.async_create_background_task(
            self.hass,
            mqtt.async_publish(
                self.hass,
                const.PLAYING_TOPIC.format(prefix=self.config.mqtt_prefix),
                payload,
                qos=1,
                retain=True,
            ),
            f"audiobox {self.config.name} show playing",
        )

    # --- buttons -------------------------------------------------------------

    @callback
    def _button_received(self, msg: mqtt.ReceiveMessage) -> None:
        try:
            payload = json.loads(msg.payload)
            button = payload["button"]
        except (ValueError, TypeError, KeyError):
            _LOGGER.debug(
                "%s: ignoring button payload %r", self.config.name, msg.payload
            )
            return
        if button == "playpause":
            self._schedule(self._async_play_pause, "play/pause")
        elif button in ("back", "fwd", "back_restart"):
            self._seek_pressed(button)
        elif button == "select_player" and isinstance(
            index := payload.get("player"), int
        ):
            self._schedule(partial(self._async_select_player, index), "select player")
        else:
            _LOGGER.debug("%s: unknown button %r", self.config.name, button)

    async def _async_play_pause(self) -> None:
        """Only with a card in the tray or playback, otherwise a red blink."""
        if self._controls_active():
            await self._async_call(
                MEDIA_PLAYER, "media_play_pause", {ATTR_ENTITY_ID: self._selected}
            )
        else:
            await self._async_flash("red", 1)

    @callback
    def _seek_pressed(self, button: str) -> None:
        """One seek at a time: presses until it has ended are dropped (ADR-44)."""
        if self._seek_busy:
            _LOGGER.debug("%s: %s dropped, a seek is running", self.config.name, button)
            return
        self._seek_busy = True
        if not self._controls_active():
            self._schedule(
                partial(self._async_flash, "red", const.NO_CARD_BLINK), "no card"
            )
            self._seek_free = async_call_later(
                self.hass, const.NO_CARD_BLINK, self._seek_blink_over
            )
            return
        if button == "back_restart":
            job = self._async_restart
        else:
            offset = const.SEEK_STEP if button == "fwd" else -const.SEEK_STEP
            job = partial(self._async_seek, offset)
        self._schedule(partial(self._async_seek_job, job), button)

    async def _async_seek_job(
        self, job: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        # The call returns once Music Assistant plays again, or fails after its
        # own timeout. Either way the buttons are free again.
        try:
            await job()
        finally:
            self._seek_busy = False

    @callback
    def _seek_blink_over(self, _now: datetime) -> None:
        self._seek_free = None
        self._seek_busy = False

    async def _async_seek(self, offset: int) -> None:
        """Plus or minus 30 s for audiobooks, previous/next track for playlists."""
        player = self._selected
        if not player:
            return
        card = self._current_card()
        if card is not None and card.media_type == const.MEDIA_TYPE_PLAYLIST:
            service = "media_next_track" if offset > 0 else "media_previous_track"
            await self._async_call(MEDIA_PLAYER, service, {ATTR_ENTITY_ID: player})
            return

        if self.hass.states.get(player) is None:
            return
        position, duration = self._position(player)
        await self._async_call(
            MEDIA_PLAYER,
            "media_seek",
            {
                ATTR_ENTITY_ID: player,
                "seek_position": self._clamp(position + offset, duration),
            },
        )

    async def _async_restart(self) -> None:
        """The book from its very beginning. Not for playlist cards.

        Without a card the item is treated as a book: Music Assistant reports
        every item as music, so a book cannot be told from a song.
        """
        player, card = self._selected, self._current_card()
        if not player or (
            card is not None and card.media_type != const.MEDIA_TYPE_AUDIOBOOK
        ):
            return
        if self.hass.states.get(player) is None:
            return
        await self._async_call(
            MEDIA_PLAYER,
            "media_seek",
            {ATTR_ENTITY_ID: player, "seek_position": const.START_POSITION},
        )

    def _current_card(self) -> Card | None:
        if self._last_card == const.NO_CARD:
            return None
        return find_card(self.entry, self._last_card)

    def _position(self, player: str) -> tuple[float, float]:
        """Where `player` is now in its item, and the item's length, in seconds."""
        state = self.hass.states.get(player)
        if state is None:
            return 0, 0
        position = float(state.attributes.get("media_position") or 0)
        duration = float(state.attributes.get("media_duration") or 0)
        # media_position is a snapshot taken at media_position_updated_at.
        updated = state.attributes.get("media_position_updated_at")
        if isinstance(updated, str):
            updated = dt_util.parse_datetime(updated)
        drift = (
            (dt_util.utcnow() - updated).total_seconds()
            if updated is not None and state.state == STATE_PLAYING
            else 0
        )
        return position + drift, duration

    @staticmethod
    def _clamp(target: float, duration: float) -> float:
        target = max(target, const.START_POSITION)
        if duration > 0:
            # Short of the end, so +30 s does not mark the book finished.
            target = min(target, duration - const.END_CLAMP)
        return target

    # --- players and volume ----------------------------------------------------

    def _choices(self) -> list[int]:
        """Players a held knob offers, as indexes into the box's list.

        The selected player first, then every free one after it in list order
        (ADR-24): available, and not selected by another box.
        """
        ids = [player.entity_id for player in self.config.players]
        if not ids:
            return []
        start = ids.index(self._selected) if self._selected in ids else 0
        taken = {
            box.selected_player
            for box in self.entry.runtime_data.boxes.values()
            if box is not self
        }
        order = [(start + step) % len(ids) for step in range(len(ids))]
        return order[:1] + [
            index
            for index in order[1:]
            if self._available(ids[index]) and ids[index] not in taken
        ]

    @callback
    def _show_choices(self) -> None:
        """Tell the box which players a held knob offers, when that changed."""
        payload = ";".join(
            f"{index}:"
            + ",".join(
                str(channel)
                for channel in const.COLOURS[self.config.players[index].colour]
            )
            for index in self._choices()
        )
        if payload == self._shown_choices:
            return
        self._shown_choices = payload
        self.entry.async_create_background_task(
            self.hass,
            mqtt.async_publish(
                self.hass,
                const.PLAYER_CHOICES_TOPIC.format(prefix=self.config.mqtt_prefix),
                payload,
                qos=1,
                retain=True,
            ),
            f"audiobox {self.config.name} show choices",
        )

    async def _async_select_player(self, index: int) -> None:
        """Move playback to the player the knob was let go on (2026-10-27).

        The box cycles through the choices it was sent; one may have gone
        since, so they are checked again. Only with a card in the tray or
        playback.
        """
        if not self._controls_active():
            await self._async_flash("red", 1)
            return
        if index not in self._choices():
            await self._async_flash("amber", 2)
            return
        current, new = self._selected, self.config.players[index].entity_id
        if new == current:
            return

        was_playing = self._is(current, STATE_PLAYING)
        if was_playing or self._is(current, STATE_PAUSED):
            card = self._current_card()
            if card is not None and card.media_type == const.MEDIA_TYPE_AUDIOBOOK:
                moved = await self._async_move_book(card, current, new, was_playing)
            else:
                moved = await self._async_move_queue(current, new, was_playing)
            if not moved:
                await self._async_flash("red", 2)
                return

        # The new player keeps its volume; the knob and the ring take it over.
        self._set_selection(new)
        colour = next(
            player.colour for player in self.config.players if player.entity_id == new
        )
        await self._async_flash(colour, 2)

    async def _async_move_book(
        self, card: Card, old: str, new: str, was_playing: bool
    ) -> bool:
        """Start the book again on `new` as the box's user, where it left off.

        Not transfer_queue: Music Assistant 2.10 moves the items but keeps the
        target queue's previous user, so the position went into the account of
        whoever last played on that speaker.
        """
        if was_playing:
            await self._async_try_call(
                MEDIA_PLAYER, "media_pause", {ATTR_ENTITY_ID: old}
            )
            await asyncio.sleep(const.SETTLE_SECONDS)
        position, duration = self._position(old)
        # Stop writes the position into the box user's account and frees the speaker.
        await self._async_try_call(MEDIA_PLAYER, "media_stop", {ATTR_ENTITY_ID: old})
        try:
            await self._async_call(
                MUSIC_ASSISTANT,
                "play_media",
                {
                    ATTR_ENTITY_ID: new,
                    "media_id": card.media_id,
                    "enqueue": "replace",
                    "username": self.config.ma_user,
                },
            )
        except HomeAssistantError as err:
            _LOGGER.warning(
                "%s: moving %s to %s failed: %s", self.config.name, card.name, new, err
            )
            return False
        if not await self._async_wait_for(
            new, STATE_PLAYING, const.PLAY_CONFIRM_SECONDS
        ):
            return False
        # The account should hold this position, but a stale or finished one must not win.
        if position > 0:
            await self._async_try_call(
                MEDIA_PLAYER,
                "media_seek",
                {ATTR_ENTITY_ID: new, "seek_position": self._clamp(position, duration)},
            )
        if not was_playing:
            await self._async_try_call(
                MEDIA_PLAYER, "media_pause", {ATTR_ENTITY_ID: new}
            )
        return True

    async def _async_move_queue(self, old: str, new: str, was_playing: bool) -> bool:
        """Anything that is not a book keeps Music Assistant's own transfer."""
        await self._async_try_call(
            MUSIC_ASSISTANT,
            "transfer_queue",
            {ATTR_ENTITY_ID: new, "source_player": old, "auto_play": was_playing},
        )
        return not was_playing or await self._async_wait_for(
            new, STATE_PLAYING, const.TRANSFER_CONFIRM_SECONDS
        )

    # --- what the box shows: the selected player's colour and volume -----------

    @callback
    def _show_selected(self) -> None:
        self.entry.async_create_background_task(
            self.hass,
            self._async_show_selected(),
            f"audiobox {self.config.name} show player",
        )
        # A player selected here is taken for every other box.
        for box in self.entry.runtime_data.boxes.values():
            box._show_choices()

    async def _async_show_selected(self) -> None:
        """The ring takes the selected player's colour, the knob its volume."""
        colour = next(
            (
                player.colour
                for player in self.config.players
                if player.entity_id == self._selected
            ),
            None,
        )
        if colour is not None:
            await mqtt.async_publish(
                self.hass,
                const.PLAYER_COLOUR_TOPIC.format(prefix=self.config.mqtt_prefix),
                ",".join(str(channel) for channel in const.COLOURS[colour]),
                qos=1,
                retain=True,
            )
        await self._async_show_volume()

    def _shown_volume(self) -> int | None:
        """The selected player's volume as the knob can show it, None if unknown."""
        state = self.hass.states.get(self._selected) if self._selected else None
        level = state.attributes.get("volume_level") if state is not None else None
        if level is None:
            return None
        shown = round(float(level) * 100)
        knob = (
            self.hass.states.get(self.config.volume_entity)
            if self.config.volume_entity
            else None
        )
        if knob is not None and (ceiling := knob.attributes.get("max")) is not None:
            # The knob's ceiling is hearing safety; the box cannot show more.
            shown = min(shown, int(ceiling))
        return shown

    def _knob_level(self) -> float | None:
        state = (
            self.hass.states.get(self.config.volume_entity)
            if self.config.volume_entity
            else None
        )
        if state is None:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    async def _async_show_volume(self) -> None:
        if self._knob_quiet is not None or not self.config.volume_entity:
            return
        shown = self._shown_volume()
        knob = self._knob_level()
        if shown is None or knob is None or round(knob) == shown:
            return
        await self._async_try_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: self.config.volume_entity, "value": shown},
        )

    @callback
    def _player_changed(self, event: Event[EventStateChangedData]) -> None:
        """A player changed, perhaps the selected one's volume in the MA app."""
        # A player that comes or goes changes what a held knob offers.
        self._show_choices()
        if event.data["entity_id"] != self._selected:
            return
        old, new = event.data["old_state"], event.data["new_state"]
        if new is not None:
            self._playback_changed(old, new)
        if new is None or (
            old is not None
            and old.attributes.get("volume_level")
            == new.attributes.get("volume_level")
        ):
            return
        self.entry.async_create_background_task(
            self.hass,
            self._async_show_volume(),
            f"audiobox {self.config.name} show volume",
        )

    @callback
    def _cancel_knob_quiet(self) -> None:
        if self._knob_quiet is not None:
            self._knob_quiet()
            self._knob_quiet = None

    @callback
    def _knob_quiet_over(self, _now: datetime) -> None:
        self._knob_quiet = None
        # Whatever the player settled on is what the knob shows.
        self.entry.async_create_background_task(
            self.hass,
            self._async_show_volume(),
            f"audiobox {self.config.name} show volume",
        )

    @callback
    def _volume_changed(self, event: Event[EventStateChangedData]) -> None:
        """Mirror the knob to the selected player. The latest value wins."""
        new = event.data["new_state"]
        if new is None:
            return
        try:
            level = float(new.state)
        except ValueError:
            return
        player = self._selected
        if level < 0 or not self._available(player):
            return
        if round(level) == self._shown_volume():
            # The knob shows the player's own volume: nothing to send back.
            return
        self._cancel_knob_quiet()
        self._knob_quiet = async_call_later(
            self.hass, const.KNOB_QUIET, self._knob_quiet_over
        )
        if self._volume_task is not None and not self._volume_task.done():
            self._volume_task.cancel()
        self._volume_task = self.entry.async_create_background_task(
            self.hass,
            self._async_try_call(
                MEDIA_PLAYER,
                "volume_set",
                {ATTR_ENTITY_ID: player, "volume_level": level / 100},
            ),
            f"audiobox {self.config.name} volume",
        )

    # --- battery -------------------------------------------------------------

    def _battery_level(self) -> float | None:
        state = (
            self.hass.states.get(self.config.battery_entity)
            if self.config.battery_entity
            else None
        )
        try:
            return float(state.state) if state is not None else None
        except ValueError:
            return None

    @callback
    def _battery_changed(self, event: Event[EventStateChangedData]) -> None:
        """Below the threshold for long enough: notify once per discharge."""
        level = self._battery_level()
        if level is not None and level < const.BATTERY_LOW_PERCENT:
            if self._battery_timer is None and not self._battery_notified:
                self._battery_timer = async_call_later(
                    self.hass, const.BATTERY_LOW_FOR, self._battery_low
                )
            return
        if level is not None:
            # Charged again: the next discharge may notify.
            self._battery_notified = False
        if self._battery_timer is not None:
            self._battery_timer()
            self._battery_timer = None

    @callback
    def _battery_low(self, _now: datetime) -> None:
        self._battery_timer = None
        if (level := self._battery_level()) is not None:
            self._battery_notified = True
            self._notify("battery_low", level=round(level))
