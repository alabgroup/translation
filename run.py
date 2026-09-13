#!/usr/bin/env python3
"""Entry point: capture the mic, transcribe, translate, and serve to OBS.

Everything runs in one process. The Flask server runs on a background thread
so the main thread can own the audio loop and handle Ctrl+C cleanly.
"""

import argparse
import threading
import time

from waitress import serve

import config
from app import audio, transcribe, transcript
from app.server import app
from app.translate import Translator


def start_server():
    """Serve the overlay pages on a daemon thread."""
    def run():
        serve(app, host=config.HOST, port=config.PORT, threads=8, _quiet=True)

    thread = threading.Thread(target=run, daemon=True, name="server")
    thread.start()
    return thread


def audio_loop(translator, stop_event):
    """Transcribe and translate each utterance until interrupted."""
    for chunk in audio.utterances(stop_event):
        duration = len(chunk) / config.SAMPLE_RATE
        started = time.time()

        text = transcribe.transcribe(chunk)
        if not text:
            continue

        translations = translator.translate(text)
        transcript.add_line(text, translations, duration)

        print(f"\n[{duration:.1f}s audio, {time.time() - started:.1f}s processing]")
        print(f"  {config.SOURCE_LANG}: {text}")
        for name, translated in translations.items():
            print(f"  {name}: {translated}")


def main():
    parser = argparse.ArgumentParser(description="Live transcription and translation for OBS")
    parser.add_argument("--list-devices", action="store_true", help="List audio input devices and exit")
    parser.add_argument("--device", help="Input device name or index (overrides config.INPUT_DEVICE)")
    parser.add_argument("--model", help="Whisper model size (overrides config.WHISPER_MODEL)")
    parser.add_argument("--no-audio", action="store_true", help="Serve the pages only, skip the mic")
    args = parser.parse_args()

    if args.list_devices:
        print("Input devices:")
        for index, name, channels in audio.list_devices():
            print(f"  [{index}] {name} ({channels} ch)")
        return

    if args.device is not None:
        config.INPUT_DEVICE = int(args.device) if args.device.isdigit() else args.device
    if args.model:
        config.WHISPER_MODEL = args.model

    start_server()
    print(f"\nControl page:  http://localhost:{config.PORT}/")
    for name in ["Source", *config.TARGET_LANGS]:
        print(f"OBS source:    http://localhost:{config.PORT}/display/{name.lower()}")

    if args.no_audio:
        print("\nRunning without audio capture. Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
        return

    translator = Translator().install_missing_packages()
    transcribe.load_model()

    stop_event = threading.Event()
    print("\nListening. Speak into the selected input. Ctrl+C to stop.\n")
    try:
        audio_loop(translator, stop_event)
    except KeyboardInterrupt:
        stop_event.set()
        print("\nStopped.")


if __name__ == "__main__":
    main()
