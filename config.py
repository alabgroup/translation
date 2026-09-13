"""Central configuration for the live translation pipeline."""

# --- Audio capture ---
# Prefer a NAME over an index: CoreAudio renumbers devices when something is
# plugged in or unplugged, so an index can select the wrong input on a later run.
INPUT_DEVICE = "NDI Audio"
NO_AUDIO_WARN_SECONDS = 30   # Warn if the input device stops delivering audio.
SAMPLE_RATE = 16000        # Whisper expects 16 kHz mono.
BLOCK_SECONDS = 0.1        # Size of each captured audio block.

# --- Utterance segmentation ---
SILENCE_RMS = 0.010        # Below this RMS a block counts as silence.
SILENCE_SECONDS = 0.7      # Silence needed to close an utterance.
MIN_UTTERANCE_SECONDS = 1.0
MAX_UTTERANCE_SECONDS = 12.0

# --- Transcription ---
WHISPER_MODEL = "small"    # tiny | base | small | medium | large-v3
WHISPER_COMPUTE = "int8"   # int8 is the fast CPU default on Apple silicon.
SOURCE_LANG = "en"

# --- Translation ---
# Display name -> target language code, used by the translator and the display page.
# Names are used in the overlay URLs (/display/spanish), so keep them URL-friendly.
# "zh" is Mandarin Chinese in simplified script.
TARGET_LANGS = {
    "Portuguese": "pt",
    "Spanish": "es",
    "Chinese": "zh",
}

# --- Live-tunable settings ---
# Exposed as sliders on the control page and changed while the service runs.
# Bounds are enforced server-side; anything not listed here needs a restart.
TUNABLE = {
    "SILENCE_SECONDS": dict(
        label="Pause before a phrase ends", unit="s", min=0.2, max=2.5, step=0.05,
        help="Shorter reacts faster but chops sentences, which translates worse."),
    "SILENCE_RMS": dict(
        label="Silence threshold", unit="", min=0.001, max=0.08, step=0.001,
        help="Set just above the room's noise floor. Watch the meter."),
    "MIN_UTTERANCE_SECONDS": dict(
        label="Shortest phrase kept", unit="s", min=0.2, max=3.0, step=0.1,
        help="Lower this to catch short responses like 'Amen'."),
    "MAX_UTTERANCE_SECONDS": dict(
        label="Longest phrase before a forced cut", unit="s", min=3, max=30, step=1,
        help="Caps the worst-case delay for a speaker who never pauses."),
    "VISIBLE_LINES": dict(
        label="Lines on the overlay", unit="", min=1, max=12, step=1),
    "CLEAR_SUBTITLES_AFTER_SECONDS": dict(
        label="Clear overlay after silence", unit="s", min=0, max=120, step=1,
        help="0 leaves the last lines on screen indefinitely."),
    "FONT_SIZE_VH": dict(
        label="Text size", unit="vh", min=1.5, max=8.0, step=0.1),
}

# --- Translation corrections ---
# Argos gets a few high-frequency words wrong, and in a service they are the
# ones said most. Each entry is (pattern, replacement) applied to that
# language's output with word boundaries. Keep this list short and specific:
# broad rewrites do more damage than the errors they fix.
TRANSLATION_FIXES = {
    # "Amen" alone translates correctly, but Whisper supplies a full stop and
    # "Amen." comes back as "Ámen." - not a Portuguese word.
    "Portuguese": [(r"\bÁmen\b", "Amém"), (r"\bAmen\b", "Amém")],
    "Spanish": [(r"\bAmen\b", "Amén")],
}

# --- Branding ---
# Shown on the control page. A passage of scripture, and passing speech
# across from one language into another.
APP_NAME = "Passage"
APP_TAGLINE = "live translation"

# Colorway per language, used for the accent wash on the control page.
# Muted, desaturated tones - they tint the interface, never shout.
LANGUAGE_COLORS = {
    "Source":     "#8E9AAF",   # Granite
    "Portuguese": "#E8875A",   # Sorrento Tangerine
    "Spanish":    "#A896E8",   # Luberon Lavender
    "Chinese":    "#5FB79A",   # Eucalyptus
}
LANGUAGE_COLOR_FALLBACK = "#8E9AAF"

# --- Server ---
HOST = "0.0.0.0"
PORT = 8000

# --- Display ---
# Clear subtitles from the overlay after this many seconds with no new speech.
# Set to 0 to leave the last lines on screen indefinitely.
CLEAR_SUBTITLES_AFTER_SECONDS = 12
VISIBLE_LINES = 8    # How many recent lines the overlay shows at once.
FONT_SIZE_VH = 4.4   # Overlay text size, in percent of canvas height.

# --- Output ---
WRITE_SRT = True           # Write transcript/translation .srt files next to the app.
