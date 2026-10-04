"""Microphone capture and utterance segmentation.

Audio arrives as small blocks from sounddevice. We buffer blocks while
someone is speaking and yield a complete utterance once the speaker pauses,
so Whisper transcribes whole phrases instead of arbitrary time slices.

Each utterance carries its position on the capture timeline, measured by
counting frames. That is the only accurate clock available: wall-clock time
after transcription has already drifted by however long Whisper took.

The input device, mute state and signal level are live: the control page reads
and changes them while the service is running.
"""

import queue
import threading
import time
import wave

import numpy as np
import sounddevice as sd

import config

_lock = threading.Lock()
_level = 0.0                        # RMS of the most recent block, for the meter.
_muted = False
_device = config.INPUT_DEVICE       # Device name or index, as configured.
_restart = threading.Event()        # Set when the capture stream must reopen.


def list_devices():
    """Return input devices as (index, name, channels) tuples."""
    devices = []
    for index, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0:
            devices.append((index, device["name"], device["max_input_channels"]))
    return devices


def _resolve_device(device):
    """Accept a device index, a partial name, or None for the default.

    Prefer names over indices: CoreAudio renumbers devices when something is
    plugged in or disconnected, so a literal index can silently select the
    wrong input or one with no input channels at all.
    """
    if device is None or isinstance(device, int):
        return device
    lowered = device.lower()
    for index, name, _ in list_devices():
        if lowered in name.lower():
            return index
    available = ", ".join(name for _, name, _ in list_devices())
    raise ValueError(f"No input device matching {device!r}. Available: {available}")


def describe_device(device=None):
    """Human-readable name of the device we will actually open."""
    if device is None:
        with _lock:
            device = _device
    resolved = _resolve_device(device)
    if resolved is None:
        resolved = sd.default.device[0]
    info = sd.query_devices(resolved)
    used = min(2, int(info["max_input_channels"]))
    return (f"[{resolved}] {info['name']} "
            f"({used} of {info['max_input_channels']} ch{', downmixed' if used > 1 else ''})")


# --- Live controls, called from the web server threads ---

def input_state():
    """Current device, mute state and signal level, for the control page."""
    with _lock:
        device, muted, level = _device, _muted, _level
    try:
        name = describe_device(device)
    except ValueError:
        name = f"{device} (not connected)"
    return {"device": device, "device_label": name, "muted": muted, "level": level}


def set_muted(value):
    global _muted
    with _lock:
        _muted = bool(value)
    return _muted


def set_device(device):
    """Switch inputs without restarting the pipeline."""
    global _device
    _resolve_device(device)          # Validate before committing to it.
    with _lock:
        _device = device
    _restart.set()
    return device


def _record_level(value):
    global _level
    with _lock:
        _level = value


_recorder = None


def _recording_file():
    """Lazily open one WAV per run, shared across device switches."""
    global _recorder
    if _recorder is None and config.RECORD_AUDIO:
        from app import transcript
        transcript.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = transcript.OUTPUT_DIR / "audio.wav"
        _recorder = wave.open(str(path), "wb")
        _recorder.setnchannels(1)
        _recorder.setsampwidth(2)          # 16-bit
        _recorder.setframerate(config.SAMPLE_RATE)
        print(f"[audio] recording to {path}")
    return _recorder


def close_recording():
    global _recorder
    if _recorder is not None:
        _recorder.close()
        _recorder = None


def utterances(stop_event):
    """Yield (audio, start_seconds, end_seconds) once per spoken utterance.

    Times are positions on the capture timeline, so they stay correct no
    matter how far transcription falls behind.
    """
    while not stop_event.is_set():
        _restart.clear()
        with _lock:
            device = _device
        try:
            yield from _capture(device, stop_event)
        except Exception as error:
            # A device can vanish mid-service. Report it and keep the pipeline
            # alive so the operator can pick another input from the web page.
            print(f"[audio] input error on {device!r}: {error}")
            _record_level(0.0)
            if not _restart.wait(timeout=2.0):
                continue


def _capture(device, stop_event):
    """Capture from one device until asked to stop or switch."""
    blocks = queue.Queue()
    block_frames = int(config.SAMPLE_RATE * config.BLOCK_SECONDS)
    overflows = 0

    resolved = _resolve_device(device)
    info = sd.query_devices(resolved if resolved is not None else sd.default.device[0])
    # Open every channel the device offers (capped at stereo) and average them.
    # Taking channel 0 alone would capture silence from a feed that carries the
    # programme audio only on the right channel.
    channels = min(2, int(info["max_input_channels"]))
    if channels < 1:
        raise ValueError(f"{info['name']!r} has no input channels")

    def on_audio(indata, _frames, _time, status):
        # This runs on the CoreAudio real-time thread. Do not print or block
        # here: a slow callback causes the very dropouts it would report.
        nonlocal overflows
        if status:
            overflows += 1
        mono = indata[:, 0] if indata.shape[1] == 1 else indata.mean(axis=1)
        blocks.put(mono.copy())

    stream = sd.InputStream(
        device=resolved,
        channels=channels,
        samplerate=config.SAMPLE_RATE,
        blocksize=block_frames,
        dtype="float32",
        callback=on_audio,
    )

    silent_timeouts_before_warning = int(config.NO_AUDIO_WARN_SECONDS / 0.25)

    buffered = []
    buffered_frames = 0
    trailing_silence = 0
    captured_frames = 0
    utterance_start = 0
    idle_timeouts = 0
    reported_overflows = 0
    warned_no_audio = False

    def finish():
        audio = np.concatenate(buffered)
        return audio, utterance_start / config.SAMPLE_RATE, captured_frames / config.SAMPLE_RATE

    print(f"[audio] capturing from {describe_device(device)}")

    with stream:
        while not stop_event.is_set() and not _restart.is_set():
            try:
                block = blocks.get(timeout=0.25)
            except queue.Empty:
                # The callback has stopped firing: the device was unplugged,
                # went to sleep, or the virtual source stopped feeding.
                _record_level(0.0)
                idle_timeouts += 1
                if not warned_no_audio and idle_timeouts >= silent_timeouts_before_warning:
                    print(f"[audio] no input for {config.NO_AUDIO_WARN_SECONDS}s "
                          f"- check the input device is still connected")
                    warned_no_audio = True
                continue

            idle_timeouts = 0
            if warned_no_audio:
                print("[audio] input resumed")
                warned_no_audio = False

            # Report dropouts from this thread, never from the callback.
            if overflows > reported_overflows:
                print(f"[audio] {overflows - reported_overflows} input overflow(s)")
                reported_overflows = overflows

            # Re-read each block: these are live-tunable from the control page.
            # round(), not int(): int(0.7 / 0.1) is 6, which would cut
            # utterances a block earlier than configured.
            silence_blocks_needed = round(config.SILENCE_SECONDS / config.BLOCK_SECONDS)
            min_frames = int(config.MIN_UTTERANCE_SECONDS * config.SAMPLE_RATE)
            max_frames = int(config.MAX_UTTERANCE_SECONDS * config.SAMPLE_RATE)
            hard_max_frames = max_frames + int(config.MAX_UTTERANCE_GRACE_SECONDS * config.SAMPLE_RATE)

            captured_frames += len(block)

            recorder = _recording_file()
            if recorder is not None:
                # float32 [-1, 1] to signed 16-bit PCM.
                clipped = np.clip(block, -1.0, 1.0)
                recorder.writeframes((clipped * 32767).astype(np.int16).tobytes())

            rms = float(np.sqrt(np.mean(block ** 2)))
            _record_level(rms)       # Meter keeps moving even while muted, so
                                     # the operator can see the feed is alive.

            with _lock:
                muted = _muted
            if muted:
                # Drop anything part-way through: resuming mid-sentence would
                # splice two unrelated moments into one utterance.
                buffered, buffered_frames, trailing_silence = [], 0, 0
                continue

            if rms < config.SILENCE_RMS and buffered_frames == 0:
                continue  # Nothing started yet; drop leading silence.

            if buffered_frames == 0:
                utterance_start = captured_frames - len(block)

            buffered.append(block)
            buffered_frames += len(block)
            trailing_silence = trailing_silence + 1 if rms < config.SILENCE_RMS else 0

            # Past max_frames, a hard cutoff would slice through the middle
            # of whatever word is being spoken - it operates on raw audio,
            # before anything is transcribed, so it has no idea where word
            # boundaries are. Instead, once over the target length, cut on
            # the next silent block: even a brief gap between words. The
            # hard ceiling still guarantees termination for a speaker who
            # never pauses at all.
            should_cut = (
                trailing_silence >= silence_blocks_needed
                or (buffered_frames >= max_frames and trailing_silence >= 1)
                or buffered_frames >= hard_max_frames
            )
            if should_cut:
                if buffered_frames >= min_frames:
                    yield finish()
                buffered, buffered_frames, trailing_silence = [], 0, 0

    # Reached on stop or device switch. Flush whatever was mid-sentence so the
    # last thing said is not lost. This must sit outside the `with stream`
    # block and outside any finally: yielding during generator teardown raises
    # "generator ignored GeneratorExit".
    _record_level(0.0)
    if buffered_frames >= int(config.MIN_UTTERANCE_SECONDS * config.SAMPLE_RATE):
        yield finish()
