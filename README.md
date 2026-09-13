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

Named `Passage` — a passage of scripture, and passing speech across from one
language into another. Rename it in `config.py` via `APP_NAME` / `APP_TAGLINE`.

Each language carries a colorway (`LANGUAGE_COLORS`), and the interface eases
to whichever one is live — so the colour of the console tells you what is on
screen without reading it.



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
- `WRITE_SRT` — write transcripts to `output/<run timestamp>/`. Each run writes
  `<language>.srt` (timed cues), `<language>.txt` (one utterance per line), and
  `transcript.jsonl` — one JSON object per utterance carrying the source, every
  translation and the timings together. Score against the JSONL; the `.txt`
  files lose the alignment between a line and its translations.
- `HALLUCINATION_PHRASES`, `MAX_NO_SPEECH_PROB`, `MIN_AVG_LOGPROB` — Whisper
  invents stock phrases ("Thank you.", "You") when handed silence. Unfiltered
  these also reset the overlay's clear timer, so subtitles never blank.

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

## Sentence assembly

A preacher pausing mid-sentence for effect produces two utterances where one
sentence was meant. Translating the first half alone wrecks the grammar in
languages that inflect for what comes later, so a fragment that does not end in
terminal punctuation is held and joined to whatever follows
(`MERGE_INCOMPLETE_SENTENCES`).

Holding is bounded: a watchdog thread releases anything held longer than
`MAX_HOLD_SECONDS`, so a speaker who simply stops mid-sentence still reaches the
screen, and `MAX_MERGED_WORDS` caps how long a merged sentence can grow. This
trades a little latency on incomplete clauses for correct grammar on complete
ones.

`WHISPER_VOCABULARY` biases transcription toward names and terms Whisper would
otherwise mishear. It is a prompt, not training — free at runtime, and the first
thing to reach for when a specific name comes out wrong.

## Evaluating accuracy

`eval.py` measures how much accuracy the live pipeline gives up for speed. It
re-transcribes a run's recorded audio with a larger Whisper model and compares
that against what the live pipeline produced.

```bash
# 1. Set RECORD_AUDIO = True in config.py, then run a service or rehearsal.
python run.py

# 2. Score the newest run.
python eval.py                       # reference: large-v3
python eval.py --model medium        # faster, cheaper reference
python eval.py output/20260913-1128  # a specific run
```

It reports word error rate split into substitutions, deletions and insertions:

- **Deletions** — speech that was said but never transcribed. Usually segmentation:
  the silence threshold is too high, or the shortest-phrase setting is dropping
  real responses.
- **Insertions** — words transcribed that were never said. Usually hallucinated
  filler on silence; extend `HALLUCINATION_PHRASES` or raise `SILENCE_RMS`.
- **Substitutions** — genuinely misheard words. This is the number a bigger
  `WHISPER_MODEL` improves.

**The bigger model is a proxy reference, not ground truth.** This answers "how
much worse is `small` than `large-v3`", which is what decides whether to change
`WHISPER_MODEL`. Absolute accuracy needs a human-written transcript — to get
that, transcribe a few minutes by hand and compare against `en.txt`.

## Tests

```bash
.venv/bin/python -m pytest -q
```

203 tests, no network and no model loading — they stub those boundaries and run
in under a second. They cover SRT timestamp maths and cue ordering, the output
files, hallucination filtering, settings validation, device resolution, the HTTP
API contract, and the WER maths in `eval.py`.

Several lock down bugs that actually shipped: negative SRT timestamps, output
written to a directory whose parent did not exist, alphabetically sorted
language order, settings partially applied from a rejected batch, and language
names resolving differently in URLs than in the API.

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
