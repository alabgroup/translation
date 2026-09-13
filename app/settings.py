"""Read and update the settings the control page can change while running.

Values live on the config module so every consumer keeps reading `config.X`
and picks up changes on its next loop, with no wiring to thread through.
"""

import threading

import config

_lock = threading.Lock()


def snapshot():
    """Current value and bounds for each tunable setting."""
    with _lock:
        return {
            name: {**spec, "value": getattr(config, name)}
            for name, spec in config.TUNABLE.items()
        }


def values():
    """Just the values, for clients that only need to apply them."""
    with _lock:
        return {name: getattr(config, name) for name in config.TUNABLE}


def update(changes):
    """Apply validated changes. Returns the values actually written."""
    applied = {}
    with _lock:
        for name, raw in changes.items():
            spec = config.TUNABLE.get(name)
            if spec is None:
                raise ValueError(f"{name!r} is not tunable while running")
            try:
                number = float(raw)
            except (TypeError, ValueError):
                raise ValueError(f"{name} must be a number, got {raw!r}")
            if not spec["min"] <= number <= spec["max"]:
                raise ValueError(
                    f"{name} must be between {spec['min']} and {spec['max']}")
            # Settings whose step is a whole number are counts, not measurements.
            if float(spec["step"]).is_integer():
                number = int(round(number))
            setattr(config, name, number)
            applied[name] = number
    return applied
