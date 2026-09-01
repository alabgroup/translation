# Running it — setup and day-of-service walkthrough

## One-time setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY (and/or DEEPL_API_KEY if you'll test that vendor)
```

Requires Python 3.10+. `sounddevice` needs PortAudio installed on the
system (macOS/Windows: bundled with the wheel; Linux: `apt install
libportaudio2` first if the pip install complains).

The first `faster-whisper` run downloads the `small.en` model
(~500MB) — do this once before a live service, not while walking on
stage.

## Starting the app

```bash
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Open **`http://localhost:8000/`** — that's the control panel. Open
**`http://localhost:8000/display`** in a second tab/window — that's the
clean projector view.

## Testing against a recording before a live service

You don't need a live mic to test the real ASR/chunking/MT pipeline —
`scripts/test_with_file.py` runs it against any audio file and prints
each committed chunk (and its translation) as it would appear live.
This is the tool for the evaluation plan in docs/SPEC.md §5: record a
real sermon, run it through this, and look at where chunk boundaries
actually landed.

```bash
python scripts/test_with_file.py path/to/sermon.mp3
python scripts/test_with_file.py path/to/sermon.wav --no-translate   # skip MT, no API key needed
python scripts/test_with_file.py sermon.mp3 --silence-threshold-ms 450 --max-chunk-duration-s 8
```

Requires `ffmpeg` on PATH for non-WAV input; a WAV file works even
without ffmpeg installed (falls back to a pure-Python resample).

## Day-of-service checklist

1. **Plug in the USB-C audio interface before starting the app** (or
   refresh the control panel's device dropdown after plugging in —
   it's populated from the OS device list at page load).
2. In the control panel's **Setup** panel: select the input device,
   confirm source/target language, pick the MT vendor, choose the
   Whisper model size (`small.en` to start — see docs/SPEC.md §3 for
   when to step up/down).
3. Click **Start**. The status pill should turn green ("listening")
   within a couple seconds — that's the Whisper model loading.
4. Do a sound check: have someone speak a sentence with a mid-sentence
   pause. You should see dim italic partial text appear in the
   **Source (live)** feed almost immediately, then a finalized
   source+translation pair appear in both feeds once the pause commits
   the chunk.
5. In OBS, add a **Browser Source** pointed at `http://localhost:8000/display`
   (or click "Open Display ↗" in the control panel and use OBS's
   window/browser capture on that window). Size it to the projector
   output.
6. **Tune chunking live, by ear, during the actual sermon's cadence** —
   this is the point of making these sliders live-editable rather than
   config-file-only:
   - Pastor talks fast with short natural pauses → lower **silence
     threshold** so phrases commit sooner.
   - Pastor runs long clauses without pausing → lower **max chunk
     duration** so the forced cut kicks in sooner rather than leaving
     the screen stale for many seconds.
   - Screen flickers/rewrites text → raise **settle buffer** slightly.
7. Stop with the **Stop** button when the service portion needing
   translation ends — this releases the audio device cleanly.

## What's genuinely tested vs. what needs a live check

Built and verified in this environment:
- All backend modules import and run correctly (syntax + logic).
- The REST API and WebSocket wiring (config get/patch, device listing,
  start/stop, broadcast) — verified with FastAPI's TestClient.
- **The chunking algorithm itself** — pause-triggered commit, the
  min-duration floor folding short blips back into the segment, and
  the max-duration fallback walking back to a clause boundary instead
  of hard-cutting — verified with a scripted fake clock and fake ASR
  hitting the exact numbers the logic should produce.
- **The real `webrtcvad` library and real chunker, against real speech
  audio** (a synthesized TTS clip, since this sandbox has no
  microphone) — confirmed VAD correctly flags speech frames and the
  max-duration fallback fires as designed on continuous speech. One
  honest caveat from that run: synthesized TTS speech has almost no
  natural pauses, so it only exercised the max-duration fallback path
  (rule 3), not the more common pause-triggered path (rule 1) — a real
  recording with natural breath pauses is needed to see rule 1 in
  action, which is exactly what the file-based harness below is for.
- The control panel and display page rendered in a real (headless)
  browser via Playwright, WebSocket-connected to the real FastAPI app,
  confirming the config-sync/live-feed/display wiring actually works —
  see the screenshots shared earlier in this session.

Blocked in this sandbox specifically (its network egress allowlist
covers GitHub/PyPI/npm/the Anthropic API, not arbitrary domains):
- Downloading real faster-whisper model weights — hosted on
  `huggingface.co`, which isn't reachable from here. ASR was tested
  structurally (imports, call signatures) but not with real weights.
- Fetching arbitrary external audio (e.g. a podcast CDN URL) to test
  against directly.

Not testable in this sandbox at all (no mic, no GPU, no live API keys
here) — needs a real run on your machine before a live service:
- Actual USB-C capture end-to-end.
- Real Whisper transcription quality/latency on your pastors' voices
  and room acoustics — including how rule 1 (pause-triggered commit)
  behaves on natural speech, not just rule 3 as seen here.
- Real Claude Haiku 4.5 / DeepL translation quality and latency —
  this is exactly the bake-off docs/SPEC.md §4 already calls for.

**`scripts/test_with_file.py`** closes most of this gap without a live
mic — point it at a real recording (a downloaded sermon, a phone
recording, whatever you have) and it runs the real ASR + chunking +
MT pipeline against it, printing each committed chunk and translation.
That's the first real test to run once you're on your own machine —
see "Testing against a recording before a live service" above.
