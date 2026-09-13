"""Microphone capture and utterance segmentation.

Audio arrives as small blocks from sounddevice. We buffer blocks while
someone is speaking and yield a complete utterance once the speaker pauses,
so Whisper transcribes whole phrases instead of arbitrary time slices.
"""

import queue

import numpy as np
import sounddevice as sd

import config


def list_devices():
    """Return input devices as (index, name, channels) tuples."""
    devices = []
    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0:
            devices.append((index, device["name"], device["max_input_channels"]))
    return devices


def _resolve_device(device):
    """Accept a device index, a partial name, or None for the default."""
    if device is None or isinstance(device, int):
        return device
    lowered = device.lower()
    for index, name, _ in list_devices():
        if lowered in name.lower():
            return index
    raise ValueError(f"No input device matching {device!r}. Run: python run.py --list-devices")


def utterances(stop_event):
    """Yield float32 mono audio arrays, one per spoken utterance."""
    blocks = queue.Queue()
    block_frames = int(config.SAMPLE_RATE * config.BLOCK_SECONDS)

    def on_audio(indata, _frames, _time, status):
        if status:
            print(f"[audio] {status}")
        blocks.put(indata[:, 0].copy())

    stream = sd.InputStream(
        device=_resolve_device(config.INPUT_DEVICE),
        channels=1,
        samplerate=config.SAMPLE_RATE,
        blocksize=block_frames,
        dtype="float32",
        callback=on_audio,
    )

    silence_blocks_needed = int(config.SILENCE_SECONDS / config.BLOCK_SECONDS)
    min_frames = int(config.MIN_UTTERANCE_SECONDS * config.SAMPLE_RATE)
    max_frames = int(config.MAX_UTTERANCE_SECONDS * config.SAMPLE_RATE)

    buffered = []
    buffered_frames = 0
    trailing_silence = 0

    with stream:
        while not stop_event.is_set():
            try:
                block = blocks.get(timeout=0.25)
            except queue.Empty:
                continue

            is_silent = float(np.sqrt(np.mean(block ** 2))) < config.SILENCE_RMS

            if is_silent and buffered_frames == 0:
                continue  # Nothing started yet; drop leading silence.

            buffered.append(block)
            buffered_frames += len(block)
            trailing_silence = trailing_silence + 1 if is_silent else 0

            ended_on_pause = trailing_silence >= silence_blocks_needed
            hit_max_length = buffered_frames >= max_frames

            if ended_on_pause or hit_max_length:
                audio = np.concatenate(buffered)
                buffered = []
                buffered_frames = 0
                trailing_silence = 0
                if len(audio) >= min_frames:
                    yield audio

    if buffered:
        yield np.concatenate(buffered)
