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

Add one **Browser Source** pointing at:

```
http://localhost:8000/display/active
```

This overlay follows whichever language is selected on the control page, so an
operator can switch languages mid-service without touching OBS. Only one
language is on screen at a time.

Set the source to the canvas size (e.g. 1920×1080). The page background is
transparent, so subtitles composite over the video.

To pin a source to one fixed language instead, use `/display/<language>` —
`/display/source`, `/display/portuguese`, `/display/spanish`, `/display/chinese`.

## Capturing computer audio instead of the mic

To subtitle audio playing on the computer (a stream, a video), route it through a
virtual audio device and select that device:

1. Install [BlackHole](https://existential.audio/blackhole/) (macOS) or
   [VB-CABLE](https://vb-audio.com/Cable/).
2. Send the app's output to that device.
3. Run `python run.py --list-devices`, then
   `python run.py --device "BlackHole 2ch"`.

## Control page

`http://localhost:8000/` is split in two: controls on the left, a live preview of
the OBS overlay on the right.

- **On screen now** — pick the language the `/display/active` overlay shows.
- **Audio input** — choose any Core Audio input, watch the level meter, and mute.
  Switching inputs reopens the capture stream without restarting the pipeline;
  muting stops transcription while leaving the meter running, so you can still
  see the feed is alive.

## Tuning during a service

The control page carries sliders for the settings worth adjusting against a real
room. They apply immediately - the capture loop re-reads them every 100 ms block
and the overlay picks them up on its next poll, so nothing restarts.

| Slider | Effect |
| --- | --- |
| Pause before a phrase ends | The main latency dial. Shorter reacts faster but chops sentences mid-clause, and Argos translates fragments noticeably worse |
| Silence threshold | Set just above the room's noise floor, watching the meter. Too low and phrases never finalize; too high and quiet speech is cut off |
| Shortest phrase kept | Lower to catch short responses. "Amen" alone is roughly 0.4 s of speech |
| Longest phrase before a forced cut | Caps worst-case delay for a speaker who does not pause |
| Lines on the overlay | How much history stays on screen |
| Clear overlay after silence | 0 leaves the last lines up indefinitely |
| Text size | Overlay text, in percent of canvas height |

Note that the pause length and the shortest-phrase setting interact: trailing
silence is buffered into the utterance, so the speech itself only needs to clear
(shortest phrase - pause) to survive. Shortening the pause quietly raises the bar
for what counts as a real phrase.

Bounds are enforced server-side. Anything outside this list - the Whisper model,
the language set - needs a restart.

## Configuration

Settings live in `config.py`:

- `INPUT_DEVICE` — input name (e.g. `"NDI Audio"`). Use a name, never an index:
  Core Audio renumbers devices when hardware connects or disconnects. Stereo
  inputs are downmixed to mono.
- `TRANSLATION_FIXES` — per-language corrections applied after translation, for
  words Argos reliably gets wrong (it renders "Amen." as "Ámen." in Portuguese).
- `TARGET_LANGS` — display name → language code. Ships with Portuguese, Spanish
  and Chinese (Mandarin, simplified script). Every utterance is translated into
  all of them, so switching languages on the control page is instant. Add entries
  to translate into more; each gets its own `/display/<name>` page.
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

**First-run model download hangs at 0 bytes.** HuggingFace's Xet backend can stall
without an error. `app/transcribe.py` sets `HF_HUB_DISABLE_XET=1` to avoid it; if you
fetch models by hand, set that variable too.

**Microphone permission.** macOS prompts on first run. If it never prompts, enable
the terminal app under System Settings → Privacy & Security → Microphone.
