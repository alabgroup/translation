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

# --- Server ---
HOST = "0.0.0.0"
PORT = 8000

# --- Display ---
# Clear subtitles from the overlay after this many seconds with no new speech.
# Set to 0 to leave the last lines on screen indefinitely.
CLEAR_SUBTITLES_AFTER_SECONDS = 12
VISIBLE_LINES = 8   # How many recent lines the overlay shows at once.

# --- Output ---
WRITE_SRT = True           # Write transcript/translation .srt files next to the app.
