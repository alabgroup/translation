"""Device resolution (app/audio.py).

CoreAudio renumbers devices whenever something is plugged in, so the pipeline
resolves a partial NAME to an index at open time. Nothing here opens a stream:
``sounddevice.query_devices`` is replaced with a fixed device table.
"""

import pytest

from app import audio


# Deliberately includes output-only devices, and puts the interesting input
# device after one of them, so an off-by-one in the index mapping shows up.
FAKE_DEVICES = [
    {"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0},
    {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2},
    {"name": "NDI Audio", "max_input_channels": 2, "max_output_channels": 0},
    {"name": "BlackHole 2ch", "max_input_channels": 2, "max_output_channels": 2},
    {"name": "Studio Display Speakers", "max_input_channels": 0, "max_output_channels": 2},
]

INPUT_ONLY_NAMES = ["MacBook Pro Microphone", "NDI Audio", "BlackHole 2ch"]
OUTPUT_ONLY_NAMES = ["MacBook Pro Speakers", "Studio Display Speakers"]


@pytest.fixture(autouse=True)
def fake_devices(monkeypatch):
    """Replace the CoreAudio device table; never touch real hardware."""
    def query_devices(device=None, kind=None):
        if device is None:
            return list(FAKE_DEVICES)
        return FAKE_DEVICES[device]

    monkeypatch.setattr(audio.sd, "query_devices", query_devices)
    return FAKE_DEVICES


# --- list_devices ---

def test_list_devices_reports_index_name_and_channel_count(fake_devices):
    assert audio.list_devices() == [
        (0, "MacBook Pro Microphone", 1),
        (2, "NDI Audio", 2),
        (3, "BlackHole 2ch", 2),
    ]


def test_list_devices_excludes_devices_with_no_input_channels(fake_devices):
    listed = [name for _index, name, _channels in audio.list_devices()]

    assert listed == INPUT_ONLY_NAMES
    for name in OUTPUT_ONLY_NAMES:
        assert name not in listed


def test_list_devices_keeps_the_real_device_index_rather_than_renumbering(fake_devices):
    # "NDI Audio" sits at table position 2; skipping the speakers at position 1
    # must not shift it down to 1, or the wrong stream gets opened.
    indexes = {name: index for index, name, _channels in audio.list_devices()}
    assert indexes["NDI Audio"] == 2
    assert indexes["BlackHole 2ch"] == 3


# --- _resolve_device ---

def test_none_means_the_system_default_and_is_passed_through_unchanged():
    assert audio._resolve_device(None) is None


@pytest.mark.parametrize("index", [0, 2, 3, 99])
def test_an_integer_index_is_passed_through_unchanged(index):
    assert audio._resolve_device(index) == index


def test_an_exact_device_name_resolves_to_its_index():
    assert audio._resolve_device("NDI Audio") == 2


@pytest.mark.parametrize("name", ["NDI", "ndi", "NDI AUDIO", "ndi audio", "Ndi AuDiO"])
def test_a_partial_name_resolves_case_insensitively(name):
    assert audio._resolve_device(name) == 2


def test_a_fragment_from_the_middle_of_a_name_resolves():
    assert audio._resolve_device("blackhole") == 3
    assert audio._resolve_device("Pro Microphone") == 0


def test_the_first_matching_input_device_wins_when_a_fragment_is_ambiguous():
    # "Pro" matches only the microphone; the speakers are not input devices.
    assert audio._resolve_device("Pro") == 0


def test_an_unmatched_name_raises_valueerror_naming_the_available_devices():
    with pytest.raises(ValueError) as error:
        audio._resolve_device("Rode NT-USB")

    message = str(error.value)
    assert "Rode NT-USB" in message
    for name in INPUT_ONLY_NAMES:
        assert name in message


def test_an_output_only_device_cannot_be_selected_as_an_input():
    with pytest.raises(ValueError) as error:
        audio._resolve_device("Studio Display Speakers")

    assert "Studio Display Speakers" not in str(error.value).split("Available:")[1]


# --- describe_device / set_device ---

def test_describe_device_names_the_device_that_will_actually_be_opened():
    description = audio.describe_device("ndi")

    assert "[2]" in description
    assert "NDI Audio" in description


def test_describe_device_reports_how_many_channels_are_downmixed():
    assert "downmixed" in audio.describe_device("NDI Audio")      # 2 channels
    assert "downmixed" not in audio.describe_device("Microphone")  # 1 channel


def test_set_device_rejects_a_name_that_matches_nothing_before_committing(monkeypatch):
    monkeypatch.setattr(audio, "_device", "NDI Audio")

    with pytest.raises(ValueError):
        audio.set_device("Rode NT-USB")

    assert audio._device == "NDI Audio", "an invalid device was committed"


def test_set_device_stores_the_requested_name_not_the_resolved_index(monkeypatch):
    monkeypatch.setattr(audio, "_device", "NDI Audio")
    monkeypatch.setattr(audio, "_restart", audio.threading.Event())

    assert audio.set_device("blackhole") == "blackhole"
    assert audio._device == "blackhole"
    assert audio._restart.is_set(), "the capture stream was not asked to reopen"


def test_input_state_labels_a_disconnected_device_instead_of_raising(monkeypatch):
    monkeypatch.setattr(audio, "_device", "Rode NT-USB")

    state = audio.input_state()

    assert state["device"] == "Rode NT-USB"
    assert "not connected" in state["device_label"]
    assert set(state) == {"device", "device_label", "muted", "level"}


def test_set_muted_round_trips_through_input_state(monkeypatch):
    monkeypatch.setattr(audio, "_device", "NDI Audio")
    monkeypatch.setattr(audio, "_muted", False)

    assert audio.set_muted(True) is True
    assert audio.input_state()["muted"] is True
    assert audio.set_muted(False) is False
