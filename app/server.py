"""Flask app serving the OBS overlay pages and the live transcript API."""

from pathlib import Path

from flask import Flask, jsonify, render_template, request, abort

import config
from app import audio, transcript

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR),
            static_folder=str(STATIC_DIR), static_url_path="/static")


@app.route("/")
def index():
    return render_template(
        "index.html",
        languages=transcript.languages(),
        port=config.PORT,
        model=config.WHISPER_MODEL,
    )


@app.route("/display/active")
def display_active():
    """Overlay that follows whichever language the control page selected."""
    return render_template("display.html", language="active",
                           clear_after_seconds=config.CLEAR_SUBTITLES_AFTER_SECONDS,
                           visible_lines=config.VISIBLE_LINES)


@app.route("/display/<language>")
def display(language):
    """Overlay pinned to one language, regardless of the control page."""
    match = next((n for n in transcript.languages() if n.lower() == language.lower()), None)
    if match is None:
        abort(404, f"Unknown language {language!r}. Available: {', '.join(transcript.languages())}")
    return render_template("display.html", language=match,
                           clear_after_seconds=config.CLEAR_SUBTITLES_AFTER_SECONDS,
                           visible_lines=config.VISIBLE_LINES)


@app.route("/api/lines")
def api_lines():
    revision, lines, active = transcript.snapshot()
    return jsonify({
        "revision": revision,
        "lines": lines,
        "active": active,
        "languages": transcript.languages(),
    })


@app.route("/api/active", methods=["POST"])
def api_set_active():
    requested = (request.get_json(silent=True) or {}).get("language")
    if not requested:
        return jsonify({"error": "missing 'language'"}), 400
    try:
        active = transcript.set_active_language(requested)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"active": active})


@app.route("/api/audio")
def api_audio():
    """Input device, level and mute state, polled by the meter."""
    state = audio.input_state()
    state["devices"] = [
        {"name": name, "index": index, "channels": channels}
        for index, name, channels in audio.list_devices()
    ]
    return jsonify(state)


@app.route("/api/audio", methods=["POST"])
def api_set_audio():
    payload = request.get_json(silent=True) or {}
    changed = {}
    if "muted" in payload:
        changed["muted"] = audio.set_muted(payload["muted"])
    if payload.get("device"):
        try:
            changed["device"] = audio.set_device(payload["device"])
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
    if not changed:
        return jsonify({"error": "nothing to change"}), 400
    return jsonify(changed)


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "languages": transcript.languages(),
        "active": transcript.active_language(),
    })
