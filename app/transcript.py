"""Shared in-memory state plus .srt transcript files."""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

import config

# Each run writes into its own timestamped folder. Appending to one shared file
# would interleave the soundcheck with the service and restart cue numbering
# partway through, leaving an .srt no player can read.
OUTPUT_ROOT = Path(__file__).resolve().parent.parent / "output"
OUTPUT_DIR = OUTPUT_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")

_lock = threading.Lock()
_lines = []          # Most recent lines, newest last.
_revision = 0        # Bumped on every append so the display can poll cheaply.
_srt_index = 1
_last_end = 0.0      # End of the last cue written, to keep cues non-overlapping.

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


def resolve_language(name):
    """Canonical name for a language, matched case-insensitively.

    Display URLs accept /display/spanish, so the API must accept "spanish"
    too - the same name answering differently in two places is a trap.
    """
    if not name:
        return None
    wanted = str(name).strip().lower()
    return next((n for n in languages() if n.lower() == wanted), None)


def set_active_language(name):
    """Point the /display/active overlay at a different language."""
    global _active_language, _revision
    canonical = resolve_language(name)
    if canonical is None:
        raise ValueError(f"Unknown language {name!r}")
    with _lock:
        _active_language = canonical
        _revision += 1   # Nudge pollers so the overlay switches immediately.
    return canonical


def _srt_timestamp(seconds):
    # Clamp: a negative value formats as "-1:59:52,-394", which is not valid SRT.
    seconds = max(0.0, seconds)
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis == 1000:          # Rounding can carry into the next second.
        whole, millis = whole + 1, 0
    return f"{whole // 3600:02d}:{(whole % 3600) // 60:02d}:{whole % 60:02d},{millis:03d}"


def _write_srt(name, text, start, end):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)   # output/ is gitignored, absent on a fresh clone
    path = OUTPUT_DIR / f"{name}.srt"
    with open(path, "a", encoding="utf-8") as srt:
        srt.write(f"{_srt_index}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n\n")


def _write_txt(name, text):
    """One utterance per line, for diffing and scoring later."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_DIR / f"{name}.txt", "a", encoding="utf-8") as plain:
        plain.write(text.replace("\n", " ").strip() + "\n")


def _write_jsonl(source_text, translations, start, end):
    """Every utterance as one JSON object: source, all translations, timings.

    This is the file to score against - the .txt files lose the alignment
    between a line and its translations.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "index": _srt_index,
        "wall_time": datetime.now().isoformat(timespec="seconds"),
        "start": round(start, 3),
        "end": round(end, 3),
        "duration": round(end - start, 3),
        "source": source_text,
        "translations": translations,
    }
    with open(OUTPUT_DIR / "transcript.jsonl", "a", encoding="utf-8") as out:
        out.write(json.dumps(record, ensure_ascii=False) + "\n")


def add_line(source_text, translations, start, end):
    """Record one transcribed utterance and its translations.

    `start` and `end` are positions on the audio capture timeline, supplied by
    the capture layer. They are never derived from the clock at this point:
    transcription latency would push every cue later than the audio it labels
    and let cues overlap or go negative.
    """
    global _revision, _srt_index, _last_end

    with _lock:
        # Measured against the real, pre-clamp start: a pause long enough to
        # read as a paragraph break on the overlay, not just a breath between
        # clauses. Skipped for the very first line - there's nothing to break
        # from yet, and _last_end (0.0) would otherwise read as a huge gap.
        paragraph_break = bool(_lines) and (start - _last_end) >= config.PARAGRAPH_GAP_SECONDS

        # Cues must not overlap, even if segmentation hands back a start that
        # is just behind the previous end.
        start = max(start, _last_end)
        end = max(end, start + 0.001)
        _last_end = end

        _lines.append({
            "id": _srt_index,          # Stable key, so the overlay can diff.
            "time": datetime.now().strftime("%H:%M:%S"),
            "source": source_text,
            "translations": translations,
            "paragraph_break": paragraph_break,
        })
        del _lines[:-MAX_LINES]
        _revision += 1

        if config.WRITE_SRT:
            _write_srt(config.SOURCE_LANG, source_text, start, end)
            _write_txt(config.SOURCE_LANG, source_text)
            for name, text in translations.items():
                _write_srt(name, text, start, end)
                _write_txt(name, text)
            _write_jsonl(source_text, translations, start, end)
            _srt_index += 1


def clear_lines():
    """Wipe the in-memory feed, for clearing test content off the overlay."""
    global _revision
    with _lock:
        _lines.clear()
        _revision += 1


def snapshot():
    """Return (revision, lines, active language) for the display pages."""
    with _lock:
        return _revision, list(_lines), _active_language
