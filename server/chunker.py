"""The chunk orchestrator — implements docs/SPEC.md §5's rules for
deciding when a phrase is "done" and ready to translate:

  1. Primary boundary: a pause >= silence_threshold_ms.
  2. Settle buffer: wait a little past the pause before committing, so a
     late ASR correction doesn't force a visible on-screen retraction.
  3. Max-duration fallback: if no pause qualifies within
     max_chunk_duration_s (a run-on preacher), force a cut — but walk
     back to the nearest clause boundary (comma, or before a
     coordinating conjunction) instead of an arbitrary word.
  4. Min-duration floor: a too-short candidate boundary is folded back
     into the ongoing segment instead of fragmenting output.

This module only decides audio boundaries and emits raw (uncommitted)
partial previews. Translation and rolling MT context live in pipeline.py.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
FRAME_MS = 30
PREROLL_MS = 300
PARTIAL_INTERVAL_S = 0.5

# Words that, together with a nearby pause in the transcript, mark a
# reasonable place to force a cut when a preacher runs past
# max_chunk_duration_s without a real pause.
CLAUSE_CONJUNCTIONS = {"and", "but", "so", "because", "or", "yet"}


@dataclass
class OpenSegment:
    audio: bytearray = field(default_factory=bytearray)
    active: bool = False

    def duration_s(self) -> float:
        return len(self.audio) / (SAMPLE_RATE * BYTES_PER_SAMPLE)


class ChunkOrchestrator:
    def __init__(
        self,
        config_store,
        asr,
        on_committed: Callable[[bytes], Awaitable[None]],
        on_partial: Callable[[str], Awaitable[None]],
    ):
        self._config_store = config_store
        self._asr = asr
        self._on_committed = on_committed
        self._on_partial = on_partial

        self._segment = OpenSegment()
        self._preroll: deque[bytes] = deque()
        self._preroll_ms = 0
        self._silence_since: float | None = None
        self._last_partial_at = 0.0

    async def feed(self, frame: bytes, is_speech: bool) -> None:
        now = time.monotonic()
        cfg = self._config_store.get().chunking

        if not self._segment.active:
            self._accumulate_preroll(frame)
            if is_speech:
                self._open_segment()
            return

        self._segment.audio.extend(frame)
        if is_speech:
            self._silence_since = None
        elif self._silence_since is None:
            self._silence_since = now

        if now - self._last_partial_at >= PARTIAL_INTERVAL_S:
            self._last_partial_at = now
            asyncio.create_task(self._emit_partial())

        duration_s = self._segment.duration_s()

        if self._silence_since is not None:
            silence_ms = (now - self._silence_since) * 1000
            if silence_ms >= cfg.silence_threshold_ms:
                settled_ms = silence_ms - cfg.silence_threshold_ms
                if settled_ms >= cfg.settle_buffer_ms:
                    if duration_s >= cfg.min_chunk_duration_s:
                        await self._commit(bytes(self._segment.audio))
                        self._reset()
                        return
                    # Rule 4: too short to count as a real boundary — treat
                    # this silence as internal to the utterance and keep
                    # listening, rather than fragmenting the output.
                    self._silence_since = now

        if duration_s >= cfg.max_chunk_duration_s:
            await self._force_commit_at_boundary()

    def _accumulate_preroll(self, frame: bytes) -> None:
        self._preroll.append(frame)
        self._preroll_ms += FRAME_MS
        while self._preroll_ms > PREROLL_MS and self._preroll:
            self._preroll.popleft()
            self._preroll_ms -= FRAME_MS

    def _open_segment(self) -> None:
        self._segment = OpenSegment(active=True)
        for f in self._preroll:
            self._segment.audio.extend(f)
        self._preroll.clear()
        self._preroll_ms = 0
        self._silence_since = None

    async def _emit_partial(self) -> None:
        language = self._config_store.get().pipeline.source_language
        text = await self._asr.transcribe_partial(bytes(self._segment.audio), language)
        if text:
            await self._on_partial(text)

    async def _commit(self, audio: bytes) -> None:
        await self._on_committed(audio)

    async def _force_commit_at_boundary(self) -> None:
        audio = bytes(self._segment.audio)
        language = self._config_store.get().pipeline.source_language
        # NB: this re-transcribes the whole open buffer just to find word
        # timestamps for the boundary search; pipeline.py's normal commit
        # flow will transcribe the committed slice again. That's a
        # deliberate, small inefficiency in v1 — it only happens on the
        # (should-be-rare) forced-cut path, not the common pause path.
        _, words = await self._asr.transcribe_final(audio, language)

        cut_byte = None
        if words:
            total_end = words[-1].end
            search_start = total_end * 0.6  # only look in the back 40%
            for w in reversed(words):
                if w.start < search_start:
                    break
                token = w.word.strip().strip(",.;:").lower()
                if w.word.strip().endswith(",") or token in CLAUSE_CONJUNCTIONS:
                    cut_byte = int(w.end * SAMPLE_RATE) * BYTES_PER_SAMPLE
                    break

        if cut_byte and 0 < cut_byte < len(audio):
            committed_audio, remainder = audio[:cut_byte], audio[cut_byte:]
        else:
            committed_audio, remainder = audio, b""

        await self._commit(committed_audio)
        self._reset(carry_over=remainder)

    def _reset(self, carry_over: bytes = b"") -> None:
        self._segment = OpenSegment(active=bool(carry_over))
        if carry_over:
            self._segment.audio.extend(carry_over)
        self._silence_since = None
        self._last_partial_at = 0.0
