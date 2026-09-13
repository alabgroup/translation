"""Shared in-memory state plus .srt transcript files."""

import threading
import time
from datetime import datetime
from pathlib import Path

import config

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

_lock = threading.Lock()
_lines = []          # Most recent lines, newest last.
_revision = 0        # Bumped on every append so the display can poll cheaply.
_srt_index = 1
_started_at = None

# The language the /display/active overlay shows. Operators switch this from
# the control page mid-service, so the OBS source URL never has to change.
_active_language = next(iter(config.TARGET_LANGS), "Source")

MAX_LINES = 50


def languages():
    """Every language the overlay can show, source included."""
    return ["Source", *config.TARGET_LANGS]


def active_language():
    with _lock:
        return _active_language


def set_active_language(name):
    """Point the /display/active overlay at a different language."""
    global _active_language, _revision
    if name not in languages():
        raise ValueError(f"Unknown language {name!r}")
    with _lock:
        _active_language = name
        _revision += 1   # Nudge pollers so the overlay switches immediately.
    return name


def _srt_timestamp(seconds):
    whole = int(seconds)
    millis = int((seconds - whole) * 1000)
    return f"{whole // 3600:02d}:{(whole % 3600) // 60:02d}:{whole % 60:02d},{millis:03d}"


def _write_srt(name, text, start, end):
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"{name}.srt"
    with open(path, "a", encoding="utf-8") as srt:
        srt.write(f"{_srt_index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n\n")


def add_line(source_text, translations, duration):
    """Record one transcribed utterance and its translations."""
    global _revision, _srt_index, _started_at

    with _lock:
        now = time.time()
        if _started_at is None:
            _started_at = now - duration
        start = now - duration - _started_at
        end = now - _started_at

        _lines.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "source": source_text,
            "translations": translations,
        })
        del _lines[:-MAX_LINES]
        _revision += 1

        if config.WRITE_SRT:
            _write_srt(config.SOURCE_LANG, source_text, start, end)
            for name, text in translations.items():
                _write_srt(name, text, start, end)
            _srt_index += 1


def snapshot():
    """Return (revision, lines, active language) for the display pages."""
    with _lock:
        return _revision, list(_lines), _active_language
