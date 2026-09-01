# translation

Real-time speech translation for live preaching/teaching: USB-C audio in →
streaming transcription → translation → clean white-on-black display,
captured by OBS as a projector feed.

Full technical spec (ASR/MT vendor comparison, latency analysis, and the
chunking algorithm for handling run-on speech): [`docs/SPEC.md`](docs/SPEC.md).

**Status:** spec drafted, implementation not started. See "Open decisions"
at the end of the spec before writing pipeline code.

## Planned structure

```
server/    orchestrator: audio capture, VAD, chunking, ASR/MT client calls
display/   browser-based display page + WebSocket client
config/    chunking.yaml, display.yaml — tunable without code changes
docs/      SPEC.md and future design notes
```
