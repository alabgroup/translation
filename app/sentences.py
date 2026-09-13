"""Join fragments of a sentence before they are translated.

A speaker who pauses mid-sentence for effect produces two utterances where
one sentence was intended. Translating the first half on its own wrecks the
grammar in languages that inflect for what comes later, so a fragment that
does not end in terminal punctuation is held briefly and joined to whatever
follows.

Holding cannot be open-ended: if the speaker stops entirely, the held text
must still reach the screen. A watchdog flushes anything held too long.
"""

import threading
import time

import config


class SentenceBuffer:
    """Collects fragments and emits complete sentences.

    `emit(text, start, end)` is called from whichever thread completes the
    sentence - the audio loop, or the watchdog on a timeout.
    """

    def __init__(self, emit):
        self._emit = emit
        self._lock = threading.Lock()
        self._parts = []
        self._start = None
        self._end = None
        self._held_since = None

    @staticmethod
    def _is_complete(text):
        return bool(text) and text.rstrip()[-1:] in config.SENTENCE_ENDINGS

    def _pending_text(self):
        return " ".join(self._parts).strip()

    def _take(self):
        """Return and clear whatever is held. Caller must hold the lock."""
        text, start, end = self._pending_text(), self._start, self._end
        self._parts, self._start, self._end, self._held_since = [], None, None, None
        return text, start, end

    def add(self, text, start, end):
        """Add one transcribed utterance, emitting when the sentence closes."""
        if not config.MERGE_INCOMPLETE_SENTENCES:
            self._emit(text, start, end)
            return

        with self._lock:
            if self._start is None:
                self._start = start
            self._parts.append(text)
            self._end = end

            merged = self._pending_text()
            too_long = len(merged.split()) >= config.MAX_MERGED_WORDS
            if not (self._is_complete(merged) or too_long):
                # Hold it, and start the clock if this is the first fragment.
                self._held_since = self._held_since or time.monotonic()
                return
            ready = self._take()

        self._emit(*ready)

    def flush_if_stale(self):
        """Emit held text that has waited too long. Called by the watchdog."""
        with self._lock:
            if self._held_since is None:
                return
            if time.monotonic() - self._held_since < config.MAX_HOLD_SECONDS:
                return
            ready = self._take()
        self._emit(*ready)

    def flush(self):
        """Emit anything held, used on shutdown."""
        with self._lock:
            if not self._parts:
                return
            ready = self._take()
        self._emit(*ready)

    def watch(self, stop_event):
        """Run the staleness check until stopped. Returns the thread."""
        def loop():
            while not stop_event.wait(0.25):
                try:
                    self.flush_if_stale()
                except Exception as error:      # never kill the watchdog
                    print(f"[sentences] flush failed: {error}")

        thread = threading.Thread(target=loop, daemon=True, name="sentence-watchdog")
        thread.start()
        return thread
