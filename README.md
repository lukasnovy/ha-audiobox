# Audiobox

A Home Assistant integration for NFC card audiobook players for children.

A child puts a card in the box and the story plays. Takes it out, it pauses.
Puts it back days later, it continues where it stopped. The box itself only
reports what happened over MQTT. This integration decides what to play, and
[Music Assistant](https://www.music-assistant.io/) plays it and keeps the
position.

Everything is set up in the Home Assistant UI: the boxes, which Music Assistant
user each box plays as, the speakers a box may move playback to, and the cards.

## Requirements

- Home Assistant 2026.10 or newer, with MQTT set up.
- Music Assistant and its Home Assistant integration.
- One Music Assistant user per child, whose provider filter allows only that
  child's audiobook account. Every card on a box plays as that user, which is
  what keeps two children's positions in the same book apart.

## What the box must publish

The integration works with any MQTT device that offers:

| What | Home Assistant entity | Values |
|---|---|---|
| Card in the tray | sensor | the card UID, for example `04-a2-3f-91`, or `none` |
| Card present | binary sensor | on / off |
| Volume knob | number | 0-100 |
| Battery (optional) | sensor, device class battery | percent |
| LED | light with RGB | |

Buttons are published as events on `<prefix>/event/button`, QoS 1, with the
payload `{"button": "playpause"}`, `"back"`, `"fwd"` or `"encoder_hold"`.

## Install

1. HACS → three-dot menu → Custom repositories.
2. Add `https://github.com/lukasnovy/ha-audiobox`, type Integration.
3. Install Audiobox and restart Home Assistant.
4. Settings → Devices & services → Add integration → Audiobox.

## Set up

1. **Notification target.** Optional. Where unknown cards, a low battery and a
   box going offline are reported. Without one, notifications appear in
   Home Assistant's own list.
2. **Add box.** Pick the box's device; its entities are suggested on the next
   page. Enter the Music Assistant user and the players. The first player must
   be the box itself: every listening session starts there.
3. **Add card.** Tap a new card on any box. It blinks red and the next
   Add card form already has its UID. Pick the book or playlist in the Music
   Assistant library.

Audiobooks must be picked from the Music Assistant library
(`library://audiobook/...`). Anything else would play, but never resume, so the
form refuses it.

Adding or editing a card never interrupts a box that is playing.

## What the box does

| Control | Action |
|---|---|
| Card in | Play, or resume the same card instantly if it is still paused |
| Card out | Pause. After 10 minutes still empty: stop, which saves the position, and select the box's own player again |
| Play/pause | Toggle, only with a card in the tray |
| Back / forward | 30 s for audiobooks, previous / next track for playlists |
| Knob turn | Volume of the selected player |
| Knob long press | Move playback to the next player. A player another box has selected is skipped |

| LED | Meaning |
|---|---|
| Green | Card recognised, playing |
| Red | Unknown card, nothing to do, or playback failed |
| Amber | The selected player is unavailable, or no other player is free |
| Player colour | The player just selected with a long press |

## Development

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

## License

MIT
