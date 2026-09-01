"""Local ASR via faster-whisper (docs/SPEC.md §3 — free, local, no
venue-internet dependency; latency tradeoff accepted deliberately).

Two entry points: a cheap partial pass for the live "typing" preview,
and a fuller pass with word timestamps for committed chunks (also used
by chunker.py to find a clause boundary when the max-duration fallback
fires).
"""
from __future__ import annotations

import asyncio

import numpy as np
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
MIN_PARTIAL_SECONDS = 0.3
MIN_FINAL_SECONDS = 0.2


class ASR:
    def __init__(
        self,
        model_size: str = "small.en",
        device: str = "auto",
        compute_type: str = "int8",
    ):
        # int8 is the safe default across CPU and GPU. If you have a GPU,
        # float16 (device="cuda") is faster — worth trying once you're
        # tuning latency against a real machine, per the §7 open decisions.
        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    @staticmethod
    def _to_float(audio_bytes: bytes) -> np.ndarray:
        pcm = np.frombuffer(audio_bytes, dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0

    async def transcribe_partial(self, audio_bytes: bytes, language: str) -> str:
        audio = self._to_float(audio_bytes)
        if audio.size < SAMPLE_RATE * MIN_PARTIAL_SECONDS:
            return ""

        def _run() -> str:
            segments, _ = self._model.transcribe(
                audio,
                language=language,
                beam_size=1,
                best_of=1,
                vad_filter=False,  # we already VAD-gate upstream
                condition_on_previous_text=False,
                word_timestamps=False,
            )
            return "".join(s.text for s in segments).strip()

        return await asyncio.to_thread(_run)

    async def transcribe_final(self, audio_bytes: bytes, language: str):
        """Returns (text, words) — words carry start/end times, used by
        chunker.py to find a clause boundary on a forced max-duration cut."""
        audio = self._to_float(audio_bytes)
        if audio.size < SAMPLE_RATE * MIN_FINAL_SECONDS:
            return "", []

        def _run():
            segments, _ = self._model.transcribe(
                audio,
                language=language,
                beam_size=5,
                vad_filter=False,
                condition_on_previous_text=False,
                word_timestamps=True,
            )
            segments = list(segments)
            text = "".join(s.text for s in segments).strip()
            words = [w for s in segments for w in (s.words or [])]
            return text, words

        return await asyncio.to_thread(_run)
