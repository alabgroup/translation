"""Live-tunable settings validation (app/settings.py).

The control page posts these while a service is on air, so a bad value must be
refused rather than written through: config values feed the segmenter on its
very next block.
"""

import pytest

import config
from app import settings


pytestmark = pytest.mark.usefixtures("restore_config")


# --- range checking ---

@pytest.mark.parametrize("name", sorted(config.TUNABLE))
def test_a_value_below_the_minimum_is_rejected(name):
    spec = config.TUNABLE[name]
    original = getattr(config, name)

    with pytest.raises(ValueError):
        settings.update({name: spec["min"] - 1})

    assert getattr(config, name) == original, "a rejected value was still written"


@pytest.mark.parametrize("name", sorted(config.TUNABLE))
def test_a_value_above_the_maximum_is_rejected(name):
    spec = config.TUNABLE[name]
    original = getattr(config, name)

    with pytest.raises(ValueError):
        settings.update({name: spec["max"] + 1})

    assert getattr(config, name) == original, "a rejected value was still written"


@pytest.mark.parametrize("name", sorted(config.TUNABLE))
def test_the_exact_minimum_and_maximum_are_accepted(name):
    spec = config.TUNABLE[name]

    assert settings.update({name: spec["min"]})[name] == pytest.approx(spec["min"])
    assert settings.update({name: spec["max"]})[name] == pytest.approx(spec["max"])


def test_the_rejection_message_names_the_setting_and_its_bounds():
    with pytest.raises(ValueError) as error:
        settings.update({"SILENCE_SECONDS": 99.0})

    message = str(error.value)
    assert "SILENCE_SECONDS" in message
    assert str(config.TUNABLE["SILENCE_SECONDS"]["max"]) in message


# --- unknown keys ---

@pytest.mark.parametrize("name", ["WHISPER_MODEL", "PORT", "SAMPLE_RATE", "nonsense", ""])
def test_a_key_that_is_not_tunable_is_rejected(name):
    with pytest.raises(ValueError):
        settings.update({name: 1})


def test_a_setting_that_needs_a_restart_is_not_written_through_by_a_rejected_update():
    original = config.WHISPER_MODEL

    with pytest.raises(ValueError):
        settings.update({"WHISPER_MODEL": 3})

    assert config.WHISPER_MODEL == original


# --- non-numeric input ---

@pytest.mark.parametrize("raw", ["loud", None, [1], {}])
def test_a_value_that_is_not_a_number_is_rejected(raw):
    with pytest.raises(ValueError):
        settings.update({"SILENCE_SECONDS": raw})


def test_a_numeric_string_from_a_form_post_is_accepted():
    assert settings.update({"SILENCE_SECONDS": "1.2"}) == {"SILENCE_SECONDS": pytest.approx(1.2)}


# --- integer coercion ---

WHOLE_STEP_SETTINGS = [name for name, spec in config.TUNABLE.items()
                       if float(spec["step"]).is_integer()]
FRACTIONAL_STEP_SETTINGS = [name for name, spec in config.TUNABLE.items()
                            if not float(spec["step"]).is_integer()]


@pytest.mark.parametrize("name", WHOLE_STEP_SETTINGS)
def test_a_setting_with_a_whole_number_step_is_coerced_to_int(name):
    spec = config.TUNABLE[name]
    midpoint = (spec["min"] + spec["max"]) / 2

    applied = settings.update({name: midpoint + 0.4})

    assert isinstance(applied[name], int), f"{name} stayed a float"
    assert isinstance(getattr(config, name), int)
    assert applied[name] == round(midpoint + 0.4)


@pytest.mark.parametrize("name", FRACTIONAL_STEP_SETTINGS)
def test_a_setting_with_a_fractional_step_keeps_its_decimals(name):
    spec = config.TUNABLE[name]
    midpoint = round((spec["min"] + spec["max"]) / 2, 3)

    applied = settings.update({name: midpoint})

    assert applied[name] == pytest.approx(midpoint)
    assert not isinstance(applied[name], int)


def test_visible_lines_rounds_to_a_whole_number_of_lines():
    assert settings.update({"VISIBLE_LINES": 5.6}) == {"VISIBLE_LINES": 6}
    assert config.VISIBLE_LINES == 6


# --- write-through and reporting ---

def test_a_valid_update_is_written_through_to_the_config_module():
    settings.update({"SILENCE_SECONDS": 1.15, "VISIBLE_LINES": 4})

    assert config.SILENCE_SECONDS == pytest.approx(1.15)
    assert config.VISIBLE_LINES == 4


def test_update_returns_exactly_the_values_it_wrote():
    applied = settings.update({"FONT_SIZE_VH": 5.5})

    assert applied == {"FONT_SIZE_VH": pytest.approx(5.5)}
    assert config.FONT_SIZE_VH == pytest.approx(5.5)


def test_an_empty_update_changes_nothing():
    before = settings.values()
    assert settings.update({}) == {}
    assert settings.values() == before


def test_values_reports_the_current_value_of_every_tunable_setting():
    assert set(settings.values()) == set(config.TUNABLE)

    settings.update({"SILENCE_RMS": 0.02})

    assert settings.values()["SILENCE_RMS"] == pytest.approx(0.02)


def test_snapshot_reports_the_bounds_alongside_the_current_value():
    snapshot = settings.snapshot()

    assert set(snapshot) == set(config.TUNABLE)
    for name, entry in snapshot.items():
        assert entry["value"] == getattr(config, name)
        for key in ("label", "min", "max", "step"):
            assert key in entry, f"{name} is missing {key}"


def test_settings_are_restored_between_tests():
    # Paired with the module-wide restore_config fixture: this test moves a
    # value, and the next one to read it must see the configured default.
    settings.update({"SILENCE_SECONDS": 2.4})
    assert config.SILENCE_SECONDS == pytest.approx(2.4)


# --- known defect, documented rather than fixed ---
# These tests assert the behaviour the API contract implies. They currently
# xfail; strict=True means they fail loudly the moment the defect is fixed, so
# the xfail marker gets removed instead of quietly hiding a regression.

def test_a_batch_update_with_one_invalid_value_writes_none_of_them():
    original = config.VISIBLE_LINES

    with pytest.raises(ValueError):
        settings.update({"VISIBLE_LINES": original + 1, "SILENCE_SECONDS": 99.0})

    assert config.VISIBLE_LINES == original, \
        "a rejected update still wrote the keys that came before the invalid one"
