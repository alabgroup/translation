"""Shared fixtures.

Two rules hold everywhere in this suite:

* nothing may write into the real ``output/`` directory - every test that
  touches transcript files redirects ``transcript.OUTPUT_DIR`` at ``tmp_path``;
* nothing may load the Whisper model, open an audio device, or reach the
  network - those boundaries are always monkeypatched.

``app.transcript``, ``app.audio`` and ``config`` all keep module-level mutable
state, so every fixture that touches it uses ``monkeypatch.setattr``, which
restores the original value when the test ends.
"""

import pytest

import config
from app import transcript as transcript_module


@pytest.fixture
def transcript(tmp_path, monkeypatch):
    """The transcript module with fresh global state and a throwaway OUTPUT_DIR.

    The module accumulates cue numbering and the last cue end across calls, so
    without this reset the tests would see each other's state.
    """
    out = tmp_path / "run-20260913-120000"
    monkeypatch.setattr(transcript_module, "OUTPUT_DIR", out)
    monkeypatch.setattr(transcript_module, "_lines", [])
    monkeypatch.setattr(transcript_module, "_revision", 0)
    monkeypatch.setattr(transcript_module, "_srt_index", 1)
    monkeypatch.setattr(transcript_module, "_last_end", 0.0)
    monkeypatch.setattr(transcript_module, "_active_language",
                        next(iter(config.TARGET_LANGS), "Source"))
    return transcript_module


@pytest.fixture
def output_dir(transcript):
    """Where the transcript fixture writes its files."""
    return transcript.OUTPUT_DIR


@pytest.fixture
def restore_config():
    """Undo any mutation of the live-tunable config values after the test."""
    original = {name: getattr(config, name) for name in config.TUNABLE}
    yield config
    for name, value in original.items():
        setattr(config, name, value)
