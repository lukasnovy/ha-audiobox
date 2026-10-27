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
payload `{"button": "playpause"}`, `"back"`, `"fwd"`, `"back_restart"`, or
`{"button": "select_player", "player": 2}` with the player's index in the box's
list.

The integration keeps the volume knob at the selected player's volume, and
publishes the selected player's colour, retained, as `r,g,b` on
`<prefix>/player_colour` (for example `0,80,255`). A box can show both.
It also publishes, retained, the players a held knob offers on
`<prefix>/player_choices`: the selected one first, then the free ones after it,
as `index:r,g,b` joined by `;` (for example `1:0,80,255;2:160,0,255;0:255,255,255`).

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
3. **Pair cards.** Open **Audiobox** in the sidebar (administrators only).

## Pairing cards

Tap a card on any box. The top of the Audiobox page shows it at once. Click its
book in the list and tap the next card.

- The list is the Music Assistant library, with covers. Search by title, switch
  between audiobooks and playlists, or show only books without a card. The
  search and filters stay set for the next card and the next visit.
- A book that already has a card is greyed out and shows the card's UID.
- A card that already has a book plays it as usual. The page shows which book
  it is: click another book to give the card to it, or remove the card.
- While the page is open, an unknown card only blinks red. The notification is
  skipped, so pairing a pile of cards does not send a pile of notifications.

The **Add card** form in the integration settings still works. Use it to rename
a card or to play a playlist shuffled. A new card blinks red on the box and the
form already has its UID.

Audiobooks must come from the Music Assistant library
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
| Back held 15 s (`back_restart`) | The audiobook from its beginning. Playlists ignore it |
| Knob turn | Volume of the selected player. A change made elsewhere, in the Music Assistant app for example, moves the knob's value too |
| Knob held 5 s | The ring shows the selected player's colour, then every 2 s the next free player's, round and round. Letting go picks the one shown and moves playback there, paused if it was paused. The new player keeps its own volume; the knob takes it over. A player another box has selected is not offered. A book starts again there as the box's Music Assistant user, at the position it left off. Only with a card in the tray |

| LED | Meaning |
|---|---|
| Green | Card recognised, playing |
| Red | Unknown card, nothing to do, or playback failed |
| Amber | The selected player is unavailable, or no other player is free |
| Player colour | The player just picked with the knob |

## Development

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

## License

MIT
