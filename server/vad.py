"""Voice activity detection — the independent signal chunker.py uses for
pause boundaries (docs/SPEC.md §5), kept separate from ASR endpointing
so chunk decisions aren't hostage to ASR latency."""
from __future__ import annotations

import webrtcvad

SAMPLE_RATE = 16000


class VAD:
    def __init__(self, aggressiveness: int = 2):
        # 0 = least aggressive (more false positives on noise),
        # 3 = most aggressive (more likely to clip quiet speech).
        # 2 is a reasonable default for a PA-fed pulpit mic; tune by ear.
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, SAMPLE_RATE)
