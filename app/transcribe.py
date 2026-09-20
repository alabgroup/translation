"""Speech-to-text using faster-whisper, running locally on the CPU."""

import os
import threading

# HuggingFace's Xet download backend can hang at zero bytes on first fetch.
# Force the plain HTTP downloader, which is reliable here. Must be set before
# faster_whisper imports huggingface_hub.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from faster_whisper import WhisperModel

import config

_lock = threading.Lock()
_model = None
_model_size = None


def load_model():
    """Load the configured model once at startup and reuse it for every utterance."""
    return set_model_size(config.WHISPER_MODEL)


def set_model_size(size):
    """Switch the live model, e.g. under CPU pressure. A no-op if already active.

    Loading a new size takes a moment (real if never used this run, otherwise
    from Whisper's own cache) but nothing else about the pipeline restarts -
    the audio stream, translator and web server are untouched.
    """
    global _model, _model_size
    with _lock:
        if _model is not None and _model_size == size:
            return _model
        print(f"[whisper] loading model {size} ({config.WHISPER_COMPUTE})...")
        _model = WhisperModel(size, device="cpu", compute_type=config.WHISPER_COMPUTE)
        _model_size = size
        print(f"[whisper] ready ({size})")
        return _model


def current_model_size():
    return _model_size


def _is_hallucination(text):
    """True if the text is one of Whisper's stock responses to silence."""
    cleaned = text.strip().lower().strip(" .,!?\u2026\"'")
    return cleaned in config.HALLUCINATION_PHRASES


def transcribe(audio):
    """Transcribe one utterance. Returns stripped text, or '' if nothing was said."""
    # Use whatever model is currently active, not necessarily config.WHISPER_MODEL:
    # autoscale can have stepped it down, and re-resolving the configured size
    # here on every utterance would silently undo that every time.
    model = _model if _model is not None else load_model()
    segments, _info = model.transcribe(
        audio,
        language=config.SOURCE_LANG,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
        initial_prompt=config.WHISPER_VOCABULARY or None,
    )

    kept = []
    for segment in segments:
        # Whisper reports how confident it is that a segment contains speech.
        # Trust that before falling back to matching known phrases.
        if getattr(segment, "no_speech_prob", 0.0) > config.MAX_NO_SPEECH_PROB:
            continue
        if getattr(segment, "avg_logprob", 0.0) < config.MIN_AVG_LOGPROB:
            continue
        text = segment.text.strip()
        if text:
            kept.append(text)

    joined = " ".join(kept).strip()
    # A stock phrase is only a hallucination when it is the entire utterance;
    # "thank you" inside a real sentence is fine.
    return "" if not joined or _is_hallucination(joined) else joined
