#!/usr/bin/env python3
"""Entry point: capture the mic, transcribe, translate, and serve to OBS.

Everything runs in one process. The Flask server runs on a background thread
so the main thread can own the audio loop and handle Ctrl+C cleanly.
"""

import argparse
import signal
import threading
import time
import traceback

from waitress import serve

import config
from app import audio, transcribe, transcript
from app.sentences import SentenceBuffer
from app.server import app
from app.translate import Translator


def start_server():
    """Serve the overlay pages on a daemon thread."""
    def run():
        serve(app, host=config.HOST, port=config.PORT, threads=8, _quiet=True)

    thread = threading.Thread(target=run, daemon=True, name="server")
    thread.start()
    return thread


def make_emitter(translator):
    """Translate one complete sentence and publish it."""
    def emit(text, start, end):
        try:
            began = time.time()
            translations = translator.translate(text)
            transcript.add_line(text, translations, start, end)

            print(f"\n[{end - start:.1f}s audio, {time.time() - began:.1f}s translating]")
            print(f"  {config.SOURCE_LANG}: {text}")
            for name, translated in translations.items():
                print(f"  {name}: {translated}")
        except Exception:
            # Also runs on the watchdog thread, which must never die.
            print("\n[error] failed to translate one sentence:")
            traceback.print_exc()
    return emit


def audio_loop(sentences, stop_event):
    """Transcribe each utterance until asked to stop.

    One bad utterance must never end the service. Every failure is logged and
    skipped: the web server runs on a daemon thread, so an exception escaping
    here would exit the process and freeze the OBS overlay on its last lines.
    """
    for chunk, start, end in audio.utterances(stop_event):
        try:
            began = time.time()
            text = transcribe.transcribe(chunk)
            if not text:
                continue
            print(f"[heard {end - start:.1f}s in {time.time() - began:.1f}s] {text}")
            # Held until the sentence closes, so a dramatic pause does not get
            # translated as half a clause.
            sentences.add(text, start, end)
        except Exception:
            print("\n[error] skipped one utterance:")
            traceback.print_exc()


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
    print(f"OBS source:    http://localhost:{config.PORT}/display/active")
    print(f"Languages:     {', '.join(transcript.languages())}")

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

    # Handle Ctrl+C by setting the flag rather than raising. The capture loop
    # then exits normally and flushes the sentence in progress; raising instead
    # tears down the generator mid-yield and loses it.
    def on_interrupt(_signum, _frame):
        if stop_event.is_set():
            print("\nForcing exit.")
            raise SystemExit(1)
        stop_event.set()
        print("\nStopping after the current phrase. Ctrl+C again to force quit.")

    signal.signal(signal.SIGINT, on_interrupt)

    print(f"Input device:  {audio.describe_device(config.INPUT_DEVICE)}")
    print(f"Transcripts:   {transcript.OUTPUT_DIR}")
    print("\nListening. Speak into the selected input. Ctrl+C to stop.\n")
    sentences = SentenceBuffer(make_emitter(translator))
    sentences.watch(stop_event)
    audio_loop(sentences, stop_event)
    sentences.flush()          # whatever was mid-sentence when we stopped
    audio.close_recording()
    print("Stopped.")


if __name__ == "__main__":
    main()
