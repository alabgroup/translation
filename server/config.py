"""Runtime configuration: what docs/SPEC.md §5's config surface maps to.

Loaded once from config/default.yaml at startup, then held in a
thread-safe, mutable store so the control panel can patch individual
fields (chunking thresholds, display styling, language pair, ...) while
the pipeline is running, without a restart.
"""
from __future__ import annotations

import threading
from pathlib import Path

import yaml
from pydantic import BaseModel


class ChunkingConfig(BaseModel):
    silence_threshold_ms: int = 600
    settle_buffer_ms: int = 200
    max_chunk_duration_s: float = 10.0
    min_chunk_duration_s: float = 1.2
    mt_context_window: int = 2


class DisplayConfig(BaseModel):
    font_family: str = "Georgia, 'Times New Roman', serif"
    font_size_px: int = 56
    text_color: str = "#f5f5f0"
    background_color: str = "#000000"
    max_lines: int = 4
    show_live_indicator: bool = True


class PipelineConfig(BaseModel):
    source_language: str = "en"
    target_language: str = "es"
    whisper_model_size: str = "small.en"
    mt_vendor: str = "claude"  # "claude" | "deepl"
    audio_device_index: int | None = None
    glossary: dict[str, str] = {}


class RuntimeConfig(BaseModel):
    chunking: ChunkingConfig = ChunkingConfig()
    display: DisplayConfig = DisplayConfig()
    pipeline: PipelineConfig = PipelineConfig()


def load_default_config(path: Path) -> RuntimeConfig:
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
        return RuntimeConfig(**data)
    return RuntimeConfig()


def _deep_merge(base: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


class ConfigStore:
    """Thread-safe holder for the live RuntimeConfig.

    Every field is readable/writable from any request/pipeline thread;
    callers always get an isolated copy so mutation elsewhere can't
    surprise them mid-read.
    """

    def __init__(self, initial: RuntimeConfig):
        self._config = initial
        self._lock = threading.RLock()

    def get(self) -> RuntimeConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def update(self, patch: dict) -> RuntimeConfig:
        with self._lock:
            data = self._config.model_dump()
            _deep_merge(data, patch)
            self._config = RuntimeConfig(**data)
            return self._config.model_copy(deep=True)
