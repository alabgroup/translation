# translation

Real-time speech translation for live preaching/teaching: USB-C audio in →
local streaming transcription → translation → clean white-on-black
display, captured by OBS as a projector feed. A web control panel drives
it: start/stop, live source transcript + translation feed, and every
chunking/display parameter tunable while it's running.

- **Technical spec** (ASR/MT vendor comparison, latency analysis, the
  chunking algorithm and its evaluation plan): [`docs/SPEC.md`](docs/SPEC.md)
- **Setup and day-of-service walkthrough**: [`docs/RUNBOOK.md`](docs/RUNBOOK.md)

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set ANTHROPIC_API_KEY and/or DEEPL_API_KEY
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

Control panel: `http://localhost:8000/` — Display page for OBS:
`http://localhost:8000/display`. Full walkthrough in
[`docs/RUNBOOK.md`](docs/RUNBOOK.md).

## Structure

```
server/    audio capture, VAD, chunking, ASR (faster-whisper), MT
           (Claude Haiku 4.5 / DeepL), WebSocket broadcast, FastAPI app
web/       control panel (start/stop, live feeds, live-tunable params)
           and the OBS-facing display page
config/    default.yaml — starting values for everything the control
           panel can also change live
docs/      SPEC.md (design/vendor decisions), RUNBOOK.md (how to run it)
scripts/   test_with_file.py — run the real pipeline against a recorded
           file instead of a live mic (no hardware needed to evaluate)
```

## Status

v1 implemented: local Whisper ASR, the hybrid pause/max-duration
chunking algorithm, Claude Haiku 4.5 + DeepL translation behind a
swappable interface, and the full web UI. Chunking logic is covered by
scripted tests; the end-to-end audio/ASR/MT path needs a real run on
your machine (no mic hardware or GPU in the environment this was built
in) — see "What's genuinely tested" in `docs/RUNBOOK.md` before a live
service.
