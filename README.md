# translation

Live translation project — real-time subtitles for services, captured from the
microphone, transcribed with Whisper, translated offline, and displayed in OBS.

Everything runs locally on the machine. No audio leaves the computer.

## How it works

```
mic → utterance segmentation → faster-whisper → Argos Translate → Flask → OBS browser source
```

A single process (`run.py`) captures audio, waits for a natural pause, transcribes
the complete phrase, translates it, and pushes it to the browser overlay pages.

## Setup (macOS)

Requires Homebrew Python 3.11 and PortAudio.

```bash
brew install python@3.11 portaudio
git clone https://github.com/alabgroup/translation.git
cd translation
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

First run downloads the Whisper model and the Argos language package
(a few hundred MB); later runs start from the local cache.

## Run

```bash
source .venv/bin/activate
python run.py
```

Then open the control page at http://localhost:8000/ to watch the live feed and
copy the overlay URLs.

Useful flags:

| Flag | Purpose |
| --- | --- |
| `--list-devices` | Show audio input devices and exit |
| `--device "CABLE Output"` | Pick an input by name or index |
| `--model medium` | Override the Whisper model size |
| `--no-audio` | Serve the pages only, without capturing audio |

Press Ctrl+C to stop.

## OBS setup

Add a **Browser Source** for each language you want on screen:

- `http://localhost:8000/display/source` — English
- `http://localhost:8000/display/portuguese` — Portuguese

Set the source to the canvas size (e.g. 1920×1080). The page background is
transparent, so subtitles composite over the video.

## Capturing computer audio instead of the mic

To subtitle audio playing on the computer (a stream, a video), route it through a
virtual audio device and select that device:

1. Install [BlackHole](https://existential.audio/blackhole/) (macOS) or
   [VB-CABLE](https://vb-audio.com/Cable/).
2. Send the app's output to that device.
3. Run `python run.py --list-devices`, then
   `python run.py --device "BlackHole 2ch"`.

## Configuration

Settings live in `config.py`:

- `TARGET_LANGS` — display name → language code. Add entries to translate into
  more languages; each one gets its own `/display/<name>` page.
- `WHISPER_MODEL` — `tiny`/`base`/`small`/`medium`/`large-v3`. Bigger is more
  accurate and slower.
- `SILENCE_RMS`, `SILENCE_SECONDS` — how a pause is detected. Raise `SILENCE_RMS`
  in a noisy room if subtitles never finalize.
- `MAX_UTTERANCE_SECONDS` — force a cut for a speaker who does not pause.
- `WRITE_SRT` — write `.srt` transcripts to `output/`.

## Layout

| Path | Purpose |
| --- | --- |
| `run.py` | Entry point: starts the server and the audio loop |
| `config.py` | All tunable settings |
| `app/audio.py` | Mic capture and utterance segmentation |
| `app/transcribe.py` | faster-whisper speech-to-text |
| `app/translate.py` | Argos translation backend |
| `app/transcript.py` | Shared state and `.srt` output |
| `app/server.py` | Flask routes |
| `app/templates/` | Control page and OBS overlay |

## Troubleshooting

**No subtitles appear.** Check the control page feed first. If it is empty, the mic
is not being picked up — run `--list-devices` and pass `--device`.

**Subtitles never finalize.** Background noise is keeping the level above the
silence threshold. Raise `SILENCE_RMS` in `config.py`.

**Too slow.** Use a smaller `WHISPER_MODEL` (`base` or `tiny`).

**Microphone permission.** macOS prompts on first run. If it never prompts, enable
the terminal app under System Settings → Privacy & Security → Microphone.
