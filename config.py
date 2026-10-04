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
# Past MAX_UTTERANCE_SECONDS, wait for the next word gap instead of cutting
# instantly - the hard cutoff used to slice through the middle of a word.
# This bounds how much longer that can take before cutting anyway.
MAX_UTTERANCE_GRACE_SECONDS = 3.0

# --- Transcription ---
WHISPER_MODEL = "small"    # tiny | base | small | medium | large-v3
WHISPER_COMPUTE = "int8"   # int8 is the fast CPU default on Apple silicon.
SOURCE_LANG = "en"

# --- Adaptive model scaling ---
# Whisper shares the machine with other live, CPU-bound software (OBS, a
# presentation app). Under sustained pressure it can transcribe slower than
# real time, and the service falls further and further behind. Trading
# WHISPER_MODEL down for speed keeps it live; this never escalates past that
# configured size - it is a ceiling, not a target to scale up to.
AUTOSCALE_MODEL = True             # Operators can flip this live from the control page.
CPU_CHECK_SECONDS = 10
CPU_DOWNGRADE_LOAD_PER_CORE = 2.5  # Sustained load above this: step the model down.
CPU_UPGRADE_LOAD_PER_CORE = 1.2    # Sustained load below this: step back up.
CPU_DOWNGRADE_SUSTAINED_CHECKS = 2 # ~20s of real trouble before reacting.
CPU_UPGRADE_SUSTAINED_CHECKS = 6   # ~60s of calm before trusting it is over.

# --- Sentence assembly ---
# A speaker who pauses mid-sentence for effect would otherwise have the
# fragment translated on its own, which wrecks grammar in languages that need
# the whole clause. Hold a fragment that does not end in terminal punctuation
# and join it to what follows before translating.
MERGE_INCOMPLETE_SENTENCES = True
SENTENCE_ENDINGS = ".?!\u2026\u3002\uff1f\uff01"
MAX_HOLD_SECONDS = 6.0       # Emit a held fragment anyway after this long.
MAX_MERGED_WORDS = 60        # Never let a merged sentence grow past this.

# Biases Whisper toward names and terms it would otherwise mishear. This is a
# prompt, not training: cheap, immediate, and it costs nothing at runtime.
WHISPER_VOCABULARY = (
    "Alabaster Group. Scripture readings from Matthew, Mark, Luke, John, "
    "Romans, Corinthians, Ephesians, Philippians, Psalms, Isaiah, Genesis, "
    "Revelation. Amen. Hallelujah. Jesus Christ. Gospel. Congregation."
)

# --- Hallucination filtering ---
# Whisper invents stock phrases when handed silence or non-speech noise.
# Unfiltered they reset the overlay's clear timer, so subtitles never blank.
MAX_NO_SPEECH_PROB = 0.6     # Reject a segment Whisper itself doubts is speech.
MIN_AVG_LOGPROB = -1.0       # Reject low-confidence output.

# Exact matches (case- and punctuation-insensitive) that are dropped outright.
# Only phrases meaningless on their own as a whole utterance belong here.
HALLUCINATION_PHRASES = {
    "you", "thank you", "thanks", "thank you very much", "thanks for watching",
    "thank you for watching", "please subscribe", "bye", "bye bye", "okay",
    "the end", "subtitles by the amara.org community", "music", "applause",
    "silence", "beep", "blank_audio",
}

# --- Overlay formatting ---
# A silence at least this long between two utterances reads as a paragraph
# break on screen - an extra blank line, instead of stacking unrelated
# sentences with no visual seam between them.
PARAGRAPH_GAP_SECONDS = 3.0

# --- Translation ---
# Display name -> target language code, used by the translator and the display page.
# Names are used in the overlay URLs (/display/spanish), so keep them URL-friendly.
# "zh" is Mandarin Chinese in simplified script.
TARGET_LANGS = {
    "Spanish": "es",
    "Chinese": "zh",
}
# Portuguese is installed and configured below; add "Portuguese": "pt" back
# here to bring it on screen again.

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
    "Spanish":    "#E8875A",   # Sorrento Tangerine
    "Chinese":    "#5FB79A",   # Eucalyptus
    "Portuguese": "#A896E8",   # Luberon Lavender (inactive)
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

# Record the captured audio to output/<run>/audio.wav. Needed to evaluate
# accuracy afterwards, since eval.py re-transcribes that audio with a larger
# model. Off by default: it records everything the microphone hears.
RECORD_AUDIO = True
