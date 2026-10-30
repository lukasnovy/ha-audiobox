"""Constants for the Audiobox integration."""

from datetime import timedelta
import re
from typing import Final

DOMAIN: Final = "audiobox"

SUBENTRY_BOX: Final = "box"
SUBENTRY_CARD: Final = "card"

# Entry
CONF_NOTIFY_ENTITY: Final = "notify_entity"

# Box subentry. The keys are the form keys.
CONF_DEVICE_ID: Final = "device_id"
CONF_MQTT_PREFIX: Final = "mqtt_prefix"
CONF_MA_USER: Final = "ma_user"
CONF_CARD_ENTITY: Final = "card_entity"
CONF_CARD_PRESENT_ENTITY: Final = "card_present_entity"
CONF_VOLUME_ENTITY: Final = "volume_entity"
CONF_BATTERY_ENTITY: Final = "battery_entity"
CONF_LED_ENTITY: Final = "led_entity"
CONF_PLAYERS: Final = "players"
CONF_PLAYER_ENTITY: Final = "entity"
CONF_PLAYER_NAME: Final = "name"
CONF_PLAYER_COLOUR: Final = "colour"

ENTITY_KEYS: Final = (
    CONF_CARD_ENTITY,
    CONF_CARD_PRESENT_ENTITY,
    CONF_VOLUME_ENTITY,
    CONF_BATTERY_ENTITY,
    CONF_LED_ENTITY,
)

# Card subentry
CONF_UID: Final = "uid"
CONF_MEDIA: Final = "media"
CONF_SHUFFLE: Final = "shuffle"

UID_PATTERN: Final = re.compile(r"[0-9a-f]{2}(-[0-9a-f]{2}){3,9}")
MQTT_PREFIX_PATTERN: Final = re.compile(r"[^#+/\s]+(/[^#+/\s]+)*")

MEDIA_TYPE_AUDIOBOOK: Final = "audiobook"
MEDIA_TYPE_PLAYLIST: Final = "playlist"
LIBRARY_AUDIOBOOK_PREFIX: Final = "library://audiobook/"

# Sent after every tap and every change of the entry or its subentries.
SIGNAL_PANEL_UPDATE: Final = "audiobox_panel_update"

# What the box publishes
NO_CARD: Final = "none"
BUTTON_TOPIC: Final = "{prefix}/event/button"

# What the box reads: the selected player's colour as "r,g,b", retained.
PLAYER_COLOUR_TOPIC: Final = "{prefix}/player_colour"
# What the box reads: the players a held knob offers, retained, the selected one
# first, as "index:r,g,b;..." where index is the player's place in the box's list.
PLAYER_CHOICES_TOPIC: Final = "{prefix}/player_choices"
# What the box reads: "ON" while the selected player plays, or for PAUSE_HOLD
# after it was paused without a card; "OFF" otherwise. Retained. Without a card
# the box's buttons and knob work only while this is ON (2026-10-30).
PLAYING_TOPIC: Final = "{prefix}/playing"

# Timings. Code reads them as `const.NAME` so that tests can patch them.
SESSION_END = timedelta(minutes=10)
# Playback paused without a card keeps the box's controls this long.
PAUSE_HOLD = timedelta(minutes=10)
SEEK_STEP = 30
# Red blink for back/fwd without a card; the seek buttons stay blocked meanwhile.
NO_CARD_BLINK = 1.0
END_CLAMP = 5
# Music Assistant reads a seek to 0 as "no position" and resumes a book where
# its account left off, so the start of a book is 1 s.
START_POSITION = 1
SETTLE_SECONDS = 1.0
PLAY_CONFIRM_SECONDS = 10.0
TRANSFER_CONFIRM_SECONDS = 5.0
KNOB_QUIET = 3.0
BATTERY_LOW_PERCENT = 20
BATTERY_LOW_FOR = timedelta(minutes=5)

LED_BRIGHTNESS: Final = 120
FEEDBACK_COLOURS: Final = {
    "green": (0, 255, 0),
    "red": (255, 0, 0),
    "amber": (255, 150, 0),
}
# Never green, red or amber: those mean "starting", "no" and "unavailable".
PLAYER_COLOURS: Final = {
    "white": (255, 255, 255),
    "blue": (0, 80, 255),
    "purple": (160, 0, 255),
    "cyan": (0, 220, 255),
    "pink": (255, 60, 160),
}
COLOURS: Final = FEEDBACK_COLOURS | PLAYER_COLOURS
