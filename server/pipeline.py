"""Wires audio capture -> VAD -> chunker -> ASR -> translator -> broadcast.

This is the one object main.py's /api/start and /api/stop control. It
owns the live ASR model and translator instances, and the rolling
translated-context window the chunker's committed chunks are translated
against (docs/SPEC.md §5, rule 5).
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque

from .asr import ASR
from .audio_capture import AudioCapture
from .chunker import ChunkOrchestrator
from .translator import get_translator
from .vad import VAD

logger = logging.getLogger("pipeline")


class Pipeline:
    def __init__(self, config_store, hub):
        self._config_store = config_store
        self._hub = hub

        self._audio: AudioCapture | None = None
        self._vad = VAD()
        self._asr: ASR | None = None
        self._translator = None
        self._chunker: ChunkOrchestrator | None = None
        self._context: deque[str] = deque(maxlen=8)

        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        cfg = self._config_store.get().pipeline

        self._asr = ASR(model_size=cfg.whisper_model_size)
        self._translator = get_translator(cfg.mt_vendor)
        self._audio = AudioCapture(device_index=cfg.audio_device_index)
        self._chunker = ChunkOrchestrator(
            self._config_store,
            self._asr,
            on_committed=self._handle_committed,
            on_partial=self._handle_partial,
        )
        self._context.clear()

        self._audio.start()
        self._running = True
        self._task = asyncio.create_task(self._run())
        await self._hub.broadcast({"type": "status", "state": "listening"})

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._audio is not None:
            self._audio.stop()
            self._audio = None
        await self._hub.broadcast({"type": "status", "state": "idle"})

    async def _run(self) -> None:
        try:
            async for frame in self._audio.frames():
                is_speech = self._vad.is_speech(frame)
                await self._chunker.feed(frame, is_speech)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("pipeline crashed")
            self._running = False
            await self._hub.broadcast(
                {"type": "status", "state": "error", "message": "Pipeline crashed — see server logs"}
            )

    async def _handle_partial(self, text: str) -> None:
        await self._hub.broadcast({"type": "partial_source", "text": text})

    async def _handle_committed(self, audio_bytes: bytes) -> None:
        cfg = self._config_store.get().pipeline
        text, _ = await self._asr.transcribe_final(audio_bytes, cfg.source_language)
        text = text.strip()
        if not text:
            return

        translated = await self._translator.translate(
            text,
            list(self._context),
            cfg.source_language,
            cfg.target_language,
            cfg.glossary,
        )
        self._context.append(translated)

        await self._hub.broadcast(
            {
                "type": "committed",
                "source_text": text,
                "translated_text": translated,
            }
        )
