"""Flask app serving the OBS overlay pages and the live transcript API."""

from pathlib import Path

from flask import Flask, jsonify, render_template, abort

import config
from app import transcript

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR))


def _known_languages():
    """Display names the overlay can render, source language included."""
    return ["Source", *config.TARGET_LANGS]


@app.route("/")
def index():
    return render_template(
        "index.html",
        languages=_known_languages(),
        port=config.PORT,
        model=config.WHISPER_MODEL,
    )


@app.route("/display/<language>")
def display(language):
    match = next((n for n in _known_languages() if n.lower() == language.lower()), None)
    if match is None:
        abort(404, f"Unknown language {language!r}. Available: {', '.join(_known_languages())}")
    return render_template("display.html", language=match)


@app.route("/api/lines")
def api_lines():
    revision, lines = transcript.snapshot()
    return jsonify({"revision": revision, "lines": lines})


@app.route("/health")
def health():
    return jsonify({"status": "ok", "languages": _known_languages()})
