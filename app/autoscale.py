"""Adaptive Whisper model sizing under CPU pressure.

WHISPER_MODEL is a quality/speed dial, and the machine running it is not
dedicated to this service - it shares the CPU with other live, real-time
software (OBS, a presentation program). Whisper is CPU-bound: under
sustained load it transcribes slower than real time, and the service falls
further and further behind rather than recovering on its own.

This watches system load on a daemon thread and steps the live model down
the size ladder while things are bad, then back up while they are calm -
never past config.WHISPER_MODEL, which stays the ceiling the operator chose.
Hysteresis (different thresholds and dwell times for stepping down vs. up)
keeps it from flapping between sizes right at the boundary.
"""

import os
import threading

import config
from app import transcribe

# Lightest to heaviest. Whichever size config.WHISPER_MODEL names is the
# ceiling - an unrecognised name is treated as already at the top, so this
# only ever scales a known size down and back, never past it.
_LADDER = ["tiny", "base", "small", "medium", "large-v3"]

_lock = threading.Lock()
_enabled = config.AUTOSCALE_MODEL
_current_index = None   # Set on the first watch() tick, once the model is loaded.
_ceiling_index = None
_last_load_per_core = 0.0


def _ceiling():
    global _ceiling_index
    if _ceiling_index is None:
        try:
            _ceiling_index = _LADDER.index(config.WHISPER_MODEL)
        except ValueError:
            _ceiling_index = len(_LADDER) - 1
    return _ceiling_index


def is_enabled():
    with _lock:
        return _enabled


def set_enabled(value):
    """Toggle from the control page. Disabling snaps straight back to the
    configured ceiling - "off" means "always use what I configured", not
    "freeze wherever it happened to be"."""
    global _enabled, _current_index
    with _lock:
        _enabled = bool(value)
        if not _enabled and _current_index != _ceiling():
            _current_index = _ceiling()
            transcribe.set_model_size(_LADDER[_current_index])
    return _enabled


def status():
    with _lock:
        return {
            "enabled": _enabled,
            "model": transcribe.current_model_size(),
            "ceiling": _LADDER[_ceiling()],
            "load_per_core": round(_last_load_per_core, 2),
        }


def watch(stop_event):
    """Start the watcher on its own daemon thread. Call once, from the main thread."""
    thread = threading.Thread(target=_loop, args=(stop_event,), daemon=True, name="autoscale")
    thread.start()
    return thread


def _loop(stop_event):
    global _current_index, _last_load_per_core

    cores = os.cpu_count() or 1
    _current_index = _ceiling()
    high_streak = 0
    low_streak = 0

    while not stop_event.wait(config.CPU_CHECK_SECONDS):
        load1, _, _ = os.getloadavg()
        per_core = load1 / cores
        with _lock:
            _last_load_per_core = per_core
            enabled = _enabled

        if not enabled:
            high_streak = low_streak = 0
            continue

        if per_core >= config.CPU_DOWNGRADE_LOAD_PER_CORE:
            high_streak += 1
            low_streak = 0
        elif per_core <= config.CPU_UPGRADE_LOAD_PER_CORE:
            low_streak += 1
            high_streak = 0
        else:
            high_streak = low_streak = 0   # In between the two thresholds: hold.

        if high_streak >= config.CPU_DOWNGRADE_SUSTAINED_CHECKS and _current_index > 0:
            _current_index -= 1
            high_streak = 0
            size = _LADDER[_current_index]
            print(f"[autoscale] load {per_core:.1f}/core sustained - stepping down to {size!r}")
            transcribe.set_model_size(size)
        elif low_streak >= config.CPU_UPGRADE_SUSTAINED_CHECKS and _current_index < _ceiling():
            _current_index += 1
            low_streak = 0
            size = _LADDER[_current_index]
            print(f"[autoscale] load {per_core:.1f}/core calm - stepping back up to {size!r}")
            transcribe.set_model_size(size)
