"""HTTP contract (app/server.py), exercised through Flask's test client.

Nothing here binds a socket, so the live pipeline on port 8000 is untouched,
and the audio module's device calls are stubbed so no stream is ever opened.
"""

import json

import pytest

import config
from app import audio, server


EXPECTED_LANGUAGES = ["Source", *config.TARGET_LANGS]


@pytest.fixture(autouse=True)
def no_audio_hardware(monkeypatch):
    """Stub every audio call the API can reach; no device is opened."""
    monkeypatch.setattr(audio, "list_devices",
                        lambda: [(0, "MacBook Pro Microphone", 1), (2, "NDI Audio", 2)])
    monkeypatch.setattr(audio, "input_state", lambda: {
        "device": "NDI Audio", "device_label": "[2] NDI Audio (2 of 2 ch, downmixed)",
        "muted": False, "level": 0.0,
    })
    monkeypatch.setattr(audio, "describe_device", lambda device=None: "[2] NDI Audio (2 of 2 ch)")
    monkeypatch.setattr(audio, "set_device", lambda device: device)
    monkeypatch.setattr(audio, "set_muted", lambda value: bool(value))


@pytest.fixture
def client(transcript, restore_config):
    """A Flask test client over isolated transcript and settings state.

    `transcript` redirects OUTPUT_DIR at tmp_path and resets the shared line
    buffer; `restore_config` puts the tunable settings back afterwards.
    """
    server.app.config["TESTING"] = True
    with server.app.test_client() as test_client:
        yield test_client


# --- /health ---

def test_health_reports_status_languages_and_the_active_overlay_language(client):
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"status", "languages", "active"}
    assert payload["status"] == "ok"
    assert payload["languages"] == EXPECTED_LANGUAGES
    assert payload["active"] in EXPECTED_LANGUAGES


# --- /api/lines ---

def test_api_lines_returns_the_keys_the_overlay_polls_for(client):
    response = client.get("/api/lines")

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"revision", "lines", "active", "languages", "settings"}
    assert isinstance(payload["revision"], int)
    assert isinstance(payload["lines"], list)
    assert set(payload["settings"]) == set(config.TUNABLE)


def test_api_lines_preserves_the_configured_language_order_instead_of_sorting(client):
    payload = client.get("/api/lines").get_json()

    assert payload["languages"] == EXPECTED_LANGUAGES
    # Guard: if the configured order ever happened to be alphabetical this test
    # would pass for the wrong reason.
    assert EXPECTED_LANGUAGES != sorted(EXPECTED_LANGUAGES), \
        "configure a non-alphabetical language order for this test to mean anything"


def test_json_responses_are_serialised_in_insertion_order_not_key_order(client, transcript):
    # Flask sorts JSON object keys by default; that reordered the per-line
    # translations away from the order the interface lays the columns out in.
    transcript.add_line("Let us pray.", {"Spanish": "Oremos.", "Chinese": "祈祷"}, 0.0, 1.0)

    body = client.get("/api/lines").get_data(as_text=True)

    assert body.index('"Spanish"') < body.index('"Chinese"')
    assert server.app.json.sort_keys is False


def test_api_lines_shows_a_line_added_to_the_transcript(client, transcript):
    transcript.add_line("Let us pray.", {"Spanish": "Oremos."}, 0.0, 2.0)

    payload = client.get("/api/lines").get_json()

    assert payload["lines"][-1]["source"] == "Let us pray."
    assert payload["lines"][-1]["translations"]["Spanish"] == "Oremos."
    assert payload["revision"] >= 1


# --- POST /api/active ---

def test_posting_an_unknown_language_to_api_active_is_rejected_with_400(client):
    response = client.post("/api/active", json={"language": "Klingon"})

    assert response.status_code == 400
    assert "error" in response.get_json()


@pytest.mark.parametrize("language", EXPECTED_LANGUAGES)
def test_posting_a_configured_language_to_api_active_switches_the_overlay(client, language):
    response = client.post("/api/active", json={"language": language})

    assert response.status_code == 200
    assert response.get_json() == {"active": language}
    assert client.get("/health").get_json()["active"] == language


def test_posting_api_active_with_no_language_is_rejected_with_400(client):
    assert client.post("/api/active", json={}).status_code == 400


def test_a_rejected_api_active_post_leaves_the_overlay_language_alone(client):
    before = client.get("/health").get_json()["active"]

    client.post("/api/active", json={"language": "Klingon"})

    assert client.get("/health").get_json()["active"] == before


# --- POST /api/settings ---

def test_posting_an_out_of_range_setting_is_rejected_with_400(client):
    before = client.get("/api/lines").get_json()["settings"]["SILENCE_SECONDS"]

    response = client.post("/api/settings", json={"SILENCE_SECONDS": 99})

    assert response.status_code == 400
    assert "error" in response.get_json()
    assert client.get("/api/lines").get_json()["settings"]["SILENCE_SECONDS"] == before


def test_posting_a_setting_below_its_minimum_is_rejected_with_400(client):
    assert client.post("/api/settings", json={"SILENCE_RMS": -1}).status_code == 400


def test_posting_a_key_that_is_not_tunable_is_rejected_with_400(client):
    response = client.post("/api/settings", json={"WHISPER_MODEL": 1})

    assert response.status_code == 400
    assert "error" in response.get_json()


def test_posting_an_empty_settings_body_is_rejected_with_400(client):
    assert client.post("/api/settings", json={}).status_code == 400


def test_posting_a_valid_setting_applies_it_and_echoes_the_written_value(client):
    response = client.post("/api/settings", json={"VISIBLE_LINES": 6})

    assert response.status_code == 200
    assert response.get_json() == {"VISIBLE_LINES": 6}
    assert client.get("/api/lines").get_json()["settings"]["VISIBLE_LINES"] == 6


def test_get_api_settings_returns_bounds_and_current_value_for_each_setting(client):
    payload = client.get("/api/settings").get_json()

    assert set(payload) == set(config.TUNABLE)
    for entry in payload.values():
        assert {"min", "max", "step", "value"} <= set(entry)


# --- display pages ---

def test_an_unknown_display_language_returns_404(client):
    assert client.get("/display/klingon").status_code == 404


@pytest.mark.parametrize("path", ["/display/source", "/display/Source", "/display/SPANISH"])
def test_a_display_language_is_matched_case_insensitively(client, path):
    assert client.get(path).status_code == 200


def test_the_follow_the_control_page_overlay_is_always_available(client):
    assert client.get("/display/active").status_code == 200


# --- /api/audio ---

def test_api_audio_reports_the_input_state_and_the_selectable_devices(client):
    payload = client.get("/api/audio").get_json()

    assert {"device", "device_label", "muted", "level", "devices"} == set(payload)
    assert payload["devices"][0] == {"name": "MacBook Pro Microphone", "index": 0, "channels": 1}


def test_posting_an_empty_audio_body_is_rejected_with_400(client):
    assert client.post("/api/audio", json={}).status_code == 400


# --- known defects, documented rather than fixed ---
# Both assert the behaviour the API contract implies, and both currently
# xfail. strict=True makes them fail loudly once the defect is fixed, so the
# marker is removed rather than quietly masking a later regression.

def test_a_rejected_settings_post_applies_none_of_the_payload(client):
    before = client.get("/api/lines").get_json()["settings"]["VISIBLE_LINES"]

    response = client.post("/api/settings",
                           json={"VISIBLE_LINES": before + 1, "SILENCE_SECONDS": 99})

    assert response.status_code == 400
    assert client.get("/api/lines").get_json()["settings"]["VISIBLE_LINES"] == before, \
        "a 400 response still applied the valid half of the payload"


def test_api_active_accepts_a_language_name_in_the_same_casing_display_urls_accept(client):
    assert client.get("/display/spanish").status_code == 200

    assert client.post("/api/active", json={"language": "spanish"}).status_code == 200
