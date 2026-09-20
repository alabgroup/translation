#!/usr/bin/env python3
"""Capture screenshots of the interface for documentation and review.

Runs its own server on a spare port with a fixed transcript, so the images
are identical every time and a live service is never disturbed. Nothing here
touches audio hardware, the Whisper model, or the output/ directory.

    python screenshots.py              # writes docs/screenshots/
    python screenshots.py --open       # and opens the folder afterwards
"""

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

import config

PORT = 8765
ROOT = Path(__file__).resolve().parent
SHOTS = ROOT / "docs" / "screenshots"

# Fixed lines so every capture is byte-comparable against the last.
SAMPLE = [
    ("Turn with me to the book of Romans, chapter eight.",
     {"Spanish": "Vuelve conmigo al libro de Romanos, capítulo ocho.",
      "Chinese": "与我一起翻到罗马书第八章。"}),
    ("There is therefore now no condemnation for those who are in Christ Jesus.",
     {"Spanish": "Por tanto, ahora no hay condenación para los que están en Cristo Jesús.",
      "Chinese": "如今那些在基督耶稣里的就不定罪了。"}),
    ("And the people said amen.",
     {"Spanish": "Y el pueblo dijo amén.",
      "Chinese": "众人说,阿门。"}),
]


def seed():
    """Fill the transcript without touching disk or the audio stack."""
    config.WRITE_SRT = False          # keep output/ clean
    from app import transcript
    start = 0.0
    for source, translations in SAMPLE:
        transcript.add_line(source, translations, start, start + 4.0)
        start += 5.0


def stub_audio():
    """Report a plausible fixed device list, so shots do not vary by machine."""
    from app import audio
    audio.list_devices = lambda: [(0, "NDI Audio", 2), (1, "MacBook Pro Microphone", 1)]
    audio.input_state = lambda: {
        "device": "NDI Audio",
        "device_label": "[0] NDI Audio (2 of 2 ch, downmixed)",
        "muted": False,
        "level": 0.034,
    }


def serve():
    from waitress import serve as waitress_serve
    from app.server import app
    thread = threading.Thread(
        target=lambda: waitress_serve(app, host="127.0.0.1", port=PORT, threads=4, _quiet=True),
        daemon=True, name="screenshot-server")
    thread.start()

    import urllib.request
    for _ in range(50):                      # wait for it to accept connections
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=0.5).read()
            return
        except Exception:
            time.sleep(0.1)
    sys.exit("Screenshot server did not start")


def capture():
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    base = f"http://127.0.0.1:{PORT}"
    written = []

    with sync_playwright() as p:
        browser = p.chromium.launch()

        def shot(name, url, width, height, settle=1.4, full=False):
            page = browser.new_page(viewport={"width": width, "height": height},
                                    device_scale_factor=2)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(int(settle * 1000))   # let the pollers paint
            path = SHOTS / name
            page.screenshot(path=str(path), full_page=full)
            page.close()
            written.append(path)
            print(f"  {name}")

        print("Capturing:")
        shot("console.png", f"{base}/", 1600, 1000)
        shot("console-narrow.png", f"{base}/", 1100, 900)
        for language in ["Source", *config.TARGET_LANGS]:
            slug = language.lower()
            shot(f"overlay-{slug}.png", f"{base}/display/{slug}?preview=1", 1920, 1080)
        # What OBS actually composites: transparent outside the panel.
        page = browser.new_page(viewport={"width": 1920, "height": 1080},
                                device_scale_factor=1)
        page.goto(f"{base}/display/active", wait_until="domcontentloaded")
        page.wait_for_timeout(1400)
        page.screenshot(path=str(SHOTS / "overlay-transparent.png"), omit_background=True)
        page.close()
        written.append(SHOTS / "overlay-transparent.png")
        print("  overlay-transparent.png")

        browser.close()
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--open", action="store_true", help="Reveal the folder when done")
    args = parser.parse_args()

    stub_audio()
    seed()
    serve()
    written = capture()

    print(f"\n{len(written)} screenshots in {SHOTS.relative_to(ROOT)}/")
    if args.open:
        subprocess.run(["open", str(SHOTS)], check=False)


if __name__ == "__main__":
    main()
