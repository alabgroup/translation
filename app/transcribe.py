"""Speech-to-text using faster-whisper, running locally on the CPU."""

import os

# HuggingFace's Xet download backend can hang at zero bytes on first fetch.
# Force the plain HTTP downloader, which is reliable here. Must be set before
# faster_whisper imports huggingface_hub.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from faster_whisper import WhisperModel

import config

_model = None


def load_model():
    """Load the Whisper model once and reuse it for every utterance."""
    global _model
    if _model is None:
        print(f"[whisper] loading model {config.WHISPER_MODEL} ({config.WHISPER_COMPUTE})...")
        _model = WhisperModel(
            config.WHISPER_MODEL,
            device="cpu",
            compute_type=config.WHISPER_COMPUTE,
        )
        print("[whisper] ready")
    return _model


def _is_hallucination(text):
    """True if the text is one of Whisper's stock responses to silence."""
    cleaned = text.strip().lower().strip(" .,!?\u2026\"'")
    return cleaned in config.HALLUCINATION_PHRASES


def transcribe(audio):
    """Transcribe one utterance. Returns stripped text, or '' if nothing was said."""
    segments, _info = load_model().transcribe(
        audio,
        language=config.SOURCE_LANG,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=False,
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
