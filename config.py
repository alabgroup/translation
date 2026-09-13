"""Central configuration for the live translation pipeline."""

# --- Audio capture ---
INPUT_DEVICE = None        # None = system default input. Set to a device name or index.
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
TARGET_LANGS = {
    "Portuguese": "pt",
}

# --- Server ---
HOST = "0.0.0.0"
PORT = 8000

# --- Output ---
WRITE_SRT = True           # Write transcript/translation .srt files next to the app.
