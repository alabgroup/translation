"""Flask app serving the OBS overlay pages and the live transcript API."""

from pathlib import Path

from flask import Flask, jsonify, render_template, request, abort

import config
from app import transcript

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))


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
    return render_template("display.html", language="active")


@app.route("/display/<language>")
def display(language):
    """Overlay pinned to one language, regardless of the control page."""
    match = next((n for n in transcript.languages() if n.lower() == language.lower()), None)
    if match is None:
        abort(404, f"Unknown language {language!r}. Available: {', '.join(transcript.languages())}")
    return render_template("display.html", language=match)


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


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "languages": transcript.languages(),
        "active": transcript.active_language(),
    })
