"""USB-C / system audio input capture.

The USB-C interface shows up to the OS as an ordinary input device — no
special driver work needed. This module just reads it as 16kHz mono
16-bit PCM in fixed 30ms frames (the size webrtcvad requires) and hands
them to the pipeline via an async generator.
"""
from __future__ import annotations

import asyncio
import queue
import threading

import sounddevice as sd

SAMPLE_RATE = 16000
FRAME_MS = 30
BLOCKSIZE = SAMPLE_RATE * FRAME_MS // 1000  # 480 samples = 960 bytes/frame


def list_input_devices() -> list[dict]:
    """Devices with at least one input channel, for the control panel's picker."""
    devices = sd.query_devices()
    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(devices)
        if d["max_input_channels"] > 0
    ]


class AudioCapture:
    def __init__(self, device_index: int | None = None):
        self._device_index = device_index
        self._queue: "queue.Queue[bytes]" = queue.Queue()
        self._stream: sd.RawInputStream | None = None
        self._stop_event = threading.Event()

    def _callback(self, indata, frames, time_info, status):  # noqa: ARG002
        # Runs on PortAudio's own thread — keep it to just a copy + enqueue.
        self._queue.put(bytes(indata))

    def start(self) -> None:
        self._stop_event.clear()
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCKSIZE,
            device=self._device_index,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def frames(self):
        """Yields 30ms PCM frames until stop() is called."""
        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            try:
                frame = await loop.run_in_executor(None, self._queue.get, True, 0.2)
            except queue.Empty:
                continue
            yield frame
