"""Flask app serving the OBS overlay pages and the live transcript API."""

import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, abort

import config
from app import audio, autoscale, settings, transcript

# Set from run.py once the translator has finished loading. Used by the
# language manager and by /api/test-line, which pushes a manual line through
# the real pipeline without a microphone.
_translator = None


def set_translator(translator):
    global _translator
    _translator = translator


# Kept so anything still importing the old name keeps working.
set_test_translator = set_translator

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = Flask(__name__, template_folder=str(TEMPLATE_DIR),
            static_folder=str(STATIC_DIR), static_url_path="/static")
# Reload templates from disk on each request so overlay tweaks during a
# rehearsal take effect on refresh, without restarting the pipeline.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
# Preserve insertion order in JSON responses: sorted keys would list the
# languages differently from the configured order the interface uses.
app.json.sort_keys = False

# Set by run.py once the translator exists. The language endpoints need it;
# everything else works without one, so the screenshot harness and the tests
# can serve the app standalone.
_translator = None


def set_translator(translator):
    global _translator
    _translator = translator


@app.route("/")
def index():
    return render_template(
        "index.html",
        languages=transcript.languages(),
        port=config.PORT,
        model=config.WHISPER_MODEL,
        app_name=config.APP_NAME,
        tagline=config.APP_TAGLINE,
        colors={name: config.LANGUAGE_COLORS.get(name, config.LANGUAGE_COLOR_FALLBACK)
                for name in transcript.languages()},
    )


@app.route("/display/active")
def display_active():
    """Overlay that follows whichever language the control page selected."""
    return render_template("display.html", language="active",
                           preview=request.args.get("preview") == "1")


@app.route("/display/<language>")
def display(language):
    """Overlay pinned to one language, regardless of the control page."""
    match = transcript.resolve_language(language)
    if match is None:
        abort(404, f"Unknown language {language!r}. Available: {', '.join(transcript.languages())}")
    return render_template("display.html", language=match,
                           preview=request.args.get("preview") == "1")


@app.route("/api/lines")
def api_lines():
    revision, lines, active = transcript.snapshot()
    return jsonify({
        "revision": revision,
        "lines": lines,
        "active": active,
        "languages": transcript.languages(),
        "settings": settings.values(),
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


@app.route("/api/settings")
def api_settings():
    return jsonify(settings.snapshot())


@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    payload = request.get_json(silent=True) or {}
    if not payload:
        return jsonify({"error": "nothing to change"}), 400
    try:
        return jsonify(settings.update(payload))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


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


@app.route("/api/languages")
def api_languages():
    """Every language Argos offers, with what is downloaded and what is live."""
    if _translator is None:
        return jsonify({"languages": [], "error": "translator not ready"})
    options, error = _translator.available()
    for option in options:
        option["status"] = _translator.status.get(option["name"], "")
    return jsonify({"languages": options, "error": error})


@app.route("/api/languages", methods=["POST"])
def api_add_language():
    """Add or remove a language while the service runs.

    Installing downloads a package, which can take a minute, so it happens on
    a worker thread and the control page polls /api/languages for progress.
    """
    if _translator is None:
        return jsonify({"error": "translator not ready"}), 503

    payload = request.get_json(silent=True) or {}
    name, code = payload.get("name"), payload.get("code")
    if not name:
        return jsonify({"error": "missing 'name'"}), 400

    if payload.get("remove"):
        if len(config.TARGET_LANGS) <= 1:
            return jsonify({"error": "at least one language must stay active"}), 400
        _translator.remove_language(name)
        if transcript.active_language() == name:
            transcript.set_active_language("Source")
        return jsonify({"removed": name})

    if not code:
        return jsonify({"error": "missing 'code'"}), 400
    if name in config.TARGET_LANGS:
        return jsonify({"error": f"{name} is already active"}), 400

    _translator.status[name] = "installing"
    threading.Thread(target=_translator.add_language, args=(name, code),
                     daemon=True, name=f"install-{code}").start()
    return jsonify({"adding": name, "code": code}), 202
@app.route("/api/autoscale")
def api_autoscale():
    """Whether adaptive model sizing is on, and its current state."""
    return jsonify(autoscale.status())


@app.route("/api/autoscale", methods=["POST"])
def api_set_autoscale():
    payload = request.get_json(silent=True) or {}
    if "enabled" not in payload:
        return jsonify({"error": "missing 'enabled'"}), 400
    autoscale.set_enabled(payload["enabled"])
    return jsonify(autoscale.status())


@app.route("/api/test-line", methods=["POST"])
def api_test_line():
    """Push one line through the real translator, bypassing the microphone."""
    if _translator is None:
        return jsonify({"error": "translator not ready yet"}), 503
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "missing 'text'"}), 400
    translations = _translator.translate(text)
    now = time.time()
    transcript.add_line(text, translations, now, now + 1)
    return jsonify({"source": text, "translations": translations})


@app.route("/api/test-clear", methods=["POST"])
def api_test_clear():
    """Wipe the feed and overlay, undoing /api/test-line."""
    transcript.clear_lines()
    return jsonify({"cleared": True})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "languages": transcript.languages(),
        "active": transcript.active_language(),
    })
