#!/usr/bin/env python3
"""Offline test harness: run the REAL pipeline (VAD, chunking, ASR, and
optionally MT) against a pre-recorded audio file instead of a live mic.

This is exactly what docs/SPEC.md §5's evaluation plan asks for — a
repeatable way to test chunking/ASR/MT against real sermon recordings,
without needing a live service or even a microphone.

Usage:
    python scripts/test_with_file.py path/to/sermon.mp3
    python scripts/test_with_file.py path/to/sermon.wav --no-translate
    python scripts/test_with_file.py sermon.mp3 --target-lang ko --mt-vendor deepl

Requires `ffmpeg` on PATH for non-WAV input (mp3, etc). A 16kHz-or-not
mono/stereo WAV file works without ffmpeg installed — it falls back to
a pure-Python resample in that case.
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.asr import ASR  # noqa: E402
from server.chunker import BYTES_PER_SAMPLE, FRAME_MS, SAMPLE_RATE, ChunkOrchestrator  # noqa: E402
from server.config import ConfigStore, RuntimeConfig  # noqa: E402
from server.translator import get_translator  # noqa: E402
from server.vad import VAD  # noqa: E402

FRAME_BYTES = int(SAMPLE_RATE * FRAME_MS / 1000) * BYTES_PER_SAMPLE


def _resample_wav_pure_python(path: Path) -> bytes:
    import numpy as np

    with wave.open(str(path), "rb") as w:
        sr, n, sampwidth, nchannels = w.getframerate(), w.getnframes(), w.getsampwidth(), w.getnchannels()
        raw = w.readframes(n)
    if sampwidth != 2:
        raise RuntimeError(f"{path}: only 16-bit PCM WAV is supported without ffmpeg")
    pcm = np.frombuffer(raw, dtype=np.int16)
    if nchannels > 1:
        pcm = pcm.reshape(-1, nchannels).mean(axis=1).astype(np.int16)
    if sr == SAMPLE_RATE:
        return pcm.tobytes()
    duration = len(pcm) / sr
    x_old = np.linspace(0, duration, num=len(pcm))
    x_new = np.linspace(0, duration, num=int(duration * SAMPLE_RATE))
    return np.interp(x_new, x_old, pcm).astype(np.int16).tobytes()


def to_pcm16k_mono(path: Path) -> bytes:
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                    "-ar", str(SAMPLE_RATE), "-ac", "1", "-acodec", "pcm_s16le", tmp.name,
                ],
                check=True,
            )
            with wave.open(tmp.name, "rb") as w:
                return w.readframes(w.getnframes())
    except FileNotFoundError:
        if path.suffix.lower() != ".wav":
            raise RuntimeError(
                f"ffmpeg not found on PATH, and {path.name} isn't a .wav file — "
                "install ffmpeg to decode mp3/other formats."
            ) from None
        print("  (ffmpeg not found — falling back to a pure-Python WAV resample)")
        return _resample_wav_pure_python(path)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio_file", type=Path)
    parser.add_argument("--source-lang", default="en")
    parser.add_argument("--target-lang", default="es")
    parser.add_argument("--whisper-model", default="small.en")
    parser.add_argument("--mt-vendor", default="claude", choices=["claude", "deepl"])
    parser.add_argument("--no-translate", action="store_true", help="skip MT — print source text only, no API key needed")
    parser.add_argument("--vad-aggressiveness", type=int, default=2)
    parser.add_argument("--silence-threshold-ms", type=int, default=600)
    parser.add_argument("--max-chunk-duration-s", type=float, default=10.0)
    args = parser.parse_args()

    print(f"Decoding {args.audio_file} to 16kHz mono PCM...")
    pcm = to_pcm16k_mono(args.audio_file)
    n_frames = len(pcm) // FRAME_BYTES
    print(f"  {n_frames * FRAME_MS / 1000:.1f}s of audio, {n_frames} frames\n")

    print(f"Loading faster-whisper ({args.whisper_model})...")
    t0 = time.time()
    asr = ASR(model_size=args.whisper_model)
    print(f"  loaded in {time.time() - t0:.1f}s\n")

    translator = None if args.no_translate else get_translator(args.mt_vendor)
    vad = VAD(aggressiveness=args.vad_aggressiveness)
    store = ConfigStore(RuntimeConfig())
    store.update({
        "chunking": {
            "silence_threshold_ms": args.silence_threshold_ms,
            "max_chunk_duration_s": args.max_chunk_duration_s,
        }
    })

    context: list[str] = []
    chunk_num = 0

    async def on_committed(audio_bytes: bytes) -> None:
        nonlocal chunk_num
        chunk_num += 1
        text, _ = await asr.transcribe_final(audio_bytes, language=args.source_lang)
        text = text.strip()
        dur_s = len(audio_bytes) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
        if not text:
            print(f"[{chunk_num:>2}  {dur_s:4.1f}s]  (no speech detected in this chunk)")
            return
        print(f"\n[{chunk_num:>2}  {dur_s:4.1f}s]  SOURCE:     {text}")
        if translator:
            translated = await translator.translate(text, context, args.source_lang, args.target_lang, {})
            context.append(translated)
            print(f"{'':>9}TRANSLATED: {translated}")

    async def on_partial(_text: str) -> None:
        pass  # offline eval cares about committed chunks, not the live preview stream

    orch = ChunkOrchestrator(store, asr, on_committed=on_committed, on_partial=on_partial)

    label = "VAD + chunking + ASR" + ("" if args.no_translate else " + MT")
    print(f"Running through the real {label} pipeline...\n" + "-" * 70)
    speech_frames = 0
    for i in range(n_frames):
        frame = pcm[i * FRAME_BYTES:(i + 1) * FRAME_BYTES]
        is_speech = vad.is_speech(frame)
        speech_frames += is_speech
        await orch.feed(frame, is_speech)

    if orch._segment.active and len(orch._segment.audio) > 0:
        await on_committed(bytes(orch._segment.audio))

    print("-" * 70)
    pct = speech_frames / n_frames * 100 if n_frames else 0
    print(f"\n{speech_frames}/{n_frames} frames ({pct:.0f}%) marked as speech by VAD")
    print(f"{chunk_num} chunk(s) committed")


if __name__ == "__main__":
    asyncio.run(main())
