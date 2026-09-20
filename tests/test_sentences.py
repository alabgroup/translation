"""Sentence joining before translation (app/sentences.py).

A preacher who pauses mid-sentence produces two utterances where one sentence
was meant, and translating half a clause wrecks the grammar in languages that
inflect for what comes later. ``SentenceBuffer`` therefore holds a fragment
that does not end in terminal punctuation and joins it to whatever follows.

The risks these tests guard are: held text that never reaches the screen
because the speaker simply stopped; one cue growing without bound; and
``emit`` - which does the translation - being called while the buffer's lock
is held, which would stall the audio thread behind a network round trip.

Nothing here sleeps for a deadline: ``time.monotonic`` is replaced by a fake
clock, and the two watchdog tests use the smallest real wait that works.
"""

import threading
import time

import pytest

import config
from app.sentences import SentenceBuffer


# --- helpers ---

class Recorder:
    """Collects emit calls, optionally asserting the buffer's lock is free.

    ``emit`` runs translation, so the buffer must release its lock before
    calling it. A non-reentrant ``threading.Lock`` cannot be re-acquired by
    the thread already holding it, so a non-blocking acquire from inside the
    callback detects the mistake.
    """

    def __init__(self, lock=None):
        self.calls = []
        self.lock = lock
        self._mutex = threading.Lock()

    def __call__(self, text, start, end):
        if self.lock is not None:
            acquired = self.lock.acquire(blocking=False)
            assert acquired, "emit was called while the buffer's lock was held"
            self.lock.release()
        with self._mutex:
            self.calls.append((text, start, end))

    @property
    def texts(self):
        return [text for text, _start, _end in self.calls]


class FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@pytest.fixture
def merging(monkeypatch):
    """Buffering on, with the defaults the production config ships."""
    monkeypatch.setattr(config, "MERGE_INCOMPLETE_SENTENCES", True)
    return config


@pytest.fixture
def clock(monkeypatch):
    """Replace ``time.monotonic`` so hold deadlines pass without real sleeps."""
    fake = FakeClock()
    monkeypatch.setattr(time, "monotonic", fake)
    return fake


def make_buffer(check_lock=False):
    recorder = Recorder()
    buffer = SentenceBuffer(recorder)
    if check_lock:
        recorder.lock = buffer._lock
    return buffer, recorder


# --- holding an incomplete fragment ---

def test_a_fragment_without_terminal_punctuation_is_not_emitted(merging):
    buffer, emitted = make_buffer(check_lock=True)

    buffer.add("And so the Lord said unto", 1.0, 3.0)

    assert emitted.calls == []


def test_the_fragment_that_completes_the_sentence_emits_once_joined_by_one_space(merging):
    buffer, emitted = make_buffer(check_lock=True)

    buffer.add("And so the Lord said unto", 1.0, 3.0)
    buffer.add("his servant Moses.", 3.5, 5.25)

    assert emitted.calls == [("And so the Lord said unto his servant Moses.", 1.0, 5.25)]


def test_the_merged_cue_carries_the_first_start_and_the_last_end(merging):
    buffer, emitted = make_buffer()

    buffer.add("Consider", 10.0, 10.5)
    buffer.add("the lilies of the field.", 12.75, 15.5)

    _text, start, end = emitted.calls[0]
    assert (start, end) == (10.0, 15.5)


def test_a_complete_sentence_on_its_own_emits_immediately_with_its_own_timings(merging):
    buffer, emitted = make_buffer(check_lock=True)

    buffer.add("Let us pray.", 4.0, 6.0)

    assert emitted.calls == [("Let us pray.", 4.0, 6.0)]


def test_three_fragments_join_in_the_order_they_arrived(merging):
    buffer, emitted = make_buffer()

    buffer.add("Faith", 1.0, 1.5)
    buffer.add("hope", 2.0, 2.5)
    buffer.add("and love", 3.0, 3.5)
    buffer.add("abide.", 4.0, 5.0)

    assert emitted.calls == [("Faith hope and love abide.", 1.0, 5.0)]


def test_a_second_sentence_is_buffered_independently_of_the_first(merging):
    buffer, emitted = make_buffer()

    buffer.add("The first", 1.0, 2.0)
    buffer.add("sentence.", 2.0, 3.0)
    buffer.add("The second", 4.0, 5.0)
    buffer.add("sentence.", 5.0, 6.0)

    assert emitted.calls == [
        ("The first sentence.", 1.0, 3.0),
        ("The second sentence.", 4.0, 6.0),
    ]


# --- what counts as the end of a sentence ---

@pytest.mark.parametrize("ending", list(config.SENTENCE_ENDINGS))
def test_every_configured_terminal_mark_closes_the_sentence(merging, ending):
    buffer, emitted = make_buffer()

    buffer.add("Amen" + ending, 1.0, 2.0)

    assert emitted.calls == [("Amen" + ending, 1.0, 2.0)]


@pytest.mark.parametrize("ending", ["。", "？", "！"])
def test_full_width_cjk_punctuation_closes_the_sentence(merging, ending):
    # The CJK marks are full-width characters, not the ASCII ones: a naive
    # `in ".?!"` check would hold a finished Chinese sentence forever.
    buffer, emitted = make_buffer()

    buffer.add("主啊" + ending, 1.0, 2.0)

    assert emitted.texts == ["主啊" + ending]


def test_the_ellipsis_character_closes_the_sentence(merging):
    buffer, emitted = make_buffer()

    buffer.add("He hesitated…", 1.0, 2.0)

    assert emitted.texts == ["He hesitated…"]


@pytest.mark.parametrize("trailing", [" ", "  ", "\n", " \t\n"])
def test_trailing_whitespace_after_the_punctuation_still_counts_as_complete(merging, trailing):
    buffer, emitted = make_buffer()

    buffer.add("It is finished." + trailing, 1.0, 2.0)

    assert len(emitted.calls) == 1


@pytest.mark.parametrize("interior", [",", ";", ":", "-", "—"])
def test_interior_punctuation_does_not_close_the_sentence(merging, interior):
    buffer, emitted = make_buffer()

    buffer.add("Therefore" + interior, 1.0, 2.0)

    assert emitted.calls == []


# --- the size cap ---

def test_held_text_is_emitted_once_it_reaches_max_merged_words(merging, monkeypatch):
    monkeypatch.setattr(config, "MAX_MERGED_WORDS", 5)
    buffer, emitted = make_buffer(check_lock=True)

    buffer.add("one two", 1.0, 2.0)
    buffer.add("three four", 2.0, 3.0)
    assert emitted.calls == [], "four words is still under the cap"

    buffer.add("five six", 3.0, 4.0)

    assert emitted.calls == [("one two three four five six", 1.0, 4.0)]


def test_a_rambling_speaker_cannot_grow_one_cue_without_bound(merging, monkeypatch):
    monkeypatch.setattr(config, "MAX_MERGED_WORDS", 4)
    buffer, emitted = make_buffer()

    for index in range(12):
        buffer.add(f"word{index}", float(index), index + 1.0)

    assert len(emitted.calls) == 3
    assert [len(text.split()) for text in emitted.texts] == [4, 4, 4]
    assert " ".join(emitted.texts).split() == [f"word{i}" for i in range(12)]


def test_the_size_cap_resets_after_each_forced_emit(merging, monkeypatch):
    monkeypatch.setattr(config, "MAX_MERGED_WORDS", 3)
    buffer, emitted = make_buffer()

    buffer.add("a b c", 1.0, 2.0)
    buffer.add("d", 5.0, 6.0)

    assert emitted.texts == ["a b c"]
    assert buffer._start == 5.0, "the next fragment starts a fresh sentence"


# --- the hold deadline ---

def test_a_held_fragment_is_not_released_before_the_hold_deadline(merging, monkeypatch, clock):
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 5.0)
    buffer, emitted = make_buffer(check_lock=True)
    buffer.add("The speaker paused", 1.0, 2.0)

    buffer.flush_if_stale()
    clock.advance(4.999)
    buffer.flush_if_stale()

    assert emitted.calls == []


def test_a_held_fragment_is_released_once_the_hold_deadline_passes(merging, monkeypatch, clock):
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 5.0)
    buffer, emitted = make_buffer(check_lock=True)
    buffer.add("The speaker stopped here", 1.0, 2.0)

    clock.advance(5.001)
    buffer.flush_if_stale()

    assert emitted.calls == [("The speaker stopped here", 1.0, 2.0)]


def test_the_hold_clock_starts_at_the_first_fragment_not_the_latest(merging, monkeypatch, clock):
    # Otherwise a speaker feeding a fragment every few seconds could defer the
    # deadline indefinitely and never reach the screen.
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 5.0)
    buffer, emitted = make_buffer()
    buffer.add("first", 1.0, 2.0)

    clock.advance(3.0)
    buffer.add("second", 4.0, 5.0)
    clock.advance(3.0)
    buffer.flush_if_stale()

    assert emitted.calls == [("first second", 1.0, 5.0)]


def test_a_stale_flush_emits_only_once_and_leaves_nothing_behind(merging, monkeypatch, clock):
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 1.0)
    buffer, emitted = make_buffer()
    buffer.add("held text", 1.0, 2.0)
    clock.advance(2.0)

    buffer.flush_if_stale()
    buffer.flush_if_stale()
    buffer.flush()

    assert len(emitted.calls) == 1


def test_flush_if_stale_is_a_no_op_when_nothing_is_held(merging, monkeypatch, clock):
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 0.0)
    buffer, emitted = make_buffer(check_lock=True)

    clock.advance(60.0)
    buffer.flush_if_stale()

    assert emitted.calls == [], "an idle buffer must not push an empty line"


def test_flush_if_stale_is_a_no_op_after_a_completed_sentence(merging, monkeypatch, clock):
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 0.0)
    buffer, emitted = make_buffer()
    buffer.add("A whole sentence.", 1.0, 2.0)

    clock.advance(60.0)
    buffer.flush_if_stale()

    assert len(emitted.calls) == 1


# --- flush on shutdown ---

def test_flush_emits_whatever_is_held(merging):
    buffer, emitted = make_buffer(check_lock=True)
    buffer.add("cut off mid", 1.0, 2.0)
    buffer.add("sentence", 2.0, 3.0)

    buffer.flush()

    assert emitted.calls == [("cut off mid sentence", 1.0, 3.0)]


def test_flush_is_a_no_op_when_nothing_is_held(merging):
    buffer, emitted = make_buffer(check_lock=True)

    buffer.flush()

    assert emitted.calls == []


def test_flush_twice_does_not_emit_the_same_text_again(merging):
    buffer, emitted = make_buffer()
    buffer.add("trailing fragment", 1.0, 2.0)

    buffer.flush()
    buffer.flush()

    assert len(emitted.calls) == 1


# --- state resets after an emit ---

def test_the_next_fragment_after_an_emit_starts_a_fresh_sentence(merging):
    buffer, emitted = make_buffer()
    buffer.add("Done.", 1.0, 2.0)

    buffer.add("A new thought", 9.0, 10.0)
    buffer.add("finishes here.", 10.0, 11.5)

    assert emitted.calls[1] == ("A new thought finishes here.", 9.0, 11.5)


def test_internal_state_is_empty_after_an_emit(merging):
    buffer, _emitted = make_buffer()

    buffer.add("Complete.", 1.0, 2.0)

    assert buffer._parts == []
    assert buffer._start is None
    assert buffer._end is None
    assert buffer._held_since is None


def test_the_hold_clock_restarts_after_an_emit_instead_of_carrying_the_old_deadline(
        merging, monkeypatch, clock):
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 5.0)
    buffer, emitted = make_buffer()

    buffer.add("held from the start", 1.0, 2.0)
    clock.advance(4.0)
    buffer.add("and closed.", 5.0, 6.0)          # emits, clearing the clock
    buffer.add("a new fragment", 7.0, 8.0)
    clock.advance(4.5)                           # 8.5 s since the first hold
    buffer.flush_if_stale()

    assert emitted.texts == ["held from the start and closed."], (
        "the new fragment inherited the previous deadline"
    )

    clock.advance(1.0)
    buffer.flush_if_stale()
    assert emitted.texts[-1] == "a new fragment"


def test_the_hold_clock_restarts_after_a_stale_flush(merging, monkeypatch, clock):
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 5.0)
    buffer, emitted = make_buffer()

    buffer.add("first hold", 1.0, 2.0)
    clock.advance(6.0)
    buffer.flush_if_stale()
    buffer.add("second hold", 8.0, 9.0)
    clock.advance(4.0)
    buffer.flush_if_stale()

    assert emitted.texts == ["first hold"]


# --- merging switched off ---

def test_merging_disabled_emits_every_fragment_immediately(monkeypatch):
    monkeypatch.setattr(config, "MERGE_INCOMPLETE_SENTENCES", False)
    buffer, emitted = make_buffer()

    buffer.add("no punctuation here", 1.0, 2.0)
    buffer.add("nor here", 2.0, 3.0)

    assert emitted.calls == [
        ("no punctuation here", 1.0, 2.0),
        ("nor here", 2.0, 3.0),
    ]


def test_merging_disabled_holds_nothing_for_the_watchdog_or_shutdown(monkeypatch, clock):
    monkeypatch.setattr(config, "MERGE_INCOMPLETE_SENTENCES", False)
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 0.0)
    buffer, emitted = make_buffer()

    buffer.add("straight through", 1.0, 2.0)
    clock.advance(60.0)
    buffer.flush_if_stale()
    buffer.flush()

    assert len(emitted.calls) == 1


def test_merging_disabled_passes_the_text_through_unchanged(monkeypatch):
    monkeypatch.setattr(config, "MERGE_INCOMPLETE_SENTENCES", False)
    buffer, emitted = make_buffer()

    buffer.add("  spaced  out  ", 1.0, 2.0)

    assert emitted.texts == ["  spaced  out  "]


# --- threading ---

def test_emit_is_never_called_while_the_buffer_lock_is_held(merging, monkeypatch, clock):
    # emit does the translation round trip; holding the lock across it would
    # block the audio thread's next add().
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 1.0)
    monkeypatch.setattr(config, "MAX_MERGED_WORDS", 3)
    observed = []

    def emit(text, _start, _end):
        acquired = buffer._lock.acquire(blocking=False)
        observed.append(acquired)
        if acquired:
            buffer._lock.release()

    buffer = SentenceBuffer(emit)

    buffer.add("A complete sentence.", 1.0, 2.0)          # add(), complete
    buffer.add("one two three", 3.0, 4.0)                 # add(), word cap
    buffer.add("stale fragment", 5.0, 6.0)
    clock.advance(2.0)
    buffer.flush_if_stale()                               # watchdog path
    buffer.add("shutdown fragment", 7.0, 8.0)
    buffer.flush()                                        # shutdown path

    assert len(observed) == 4
    assert all(observed), "emit ran inside the lock on at least one path"


def test_concurrent_adds_lose_and_duplicate_no_fragment(merging, monkeypatch):
    monkeypatch.setattr(config, "MAX_MERGED_WORDS", 7)
    buffer, emitted = make_buffer()
    threads_count, per_thread = 8, 25
    expected = [f"t{t}w{w}" for t in range(threads_count) for w in range(per_thread)]
    start_line = threading.Barrier(threads_count)

    def speak(index):
        start_line.wait()
        for word in range(per_thread):
            buffer.add(f"t{index}w{word}", float(word), word + 1.0)

    threads = [threading.Thread(target=speak, args=(i,)) for i in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    buffer.flush()

    words = " ".join(emitted.texts).split()
    assert sorted(words) == sorted(expected)
    assert len(words) == len(set(words)), "a fragment was emitted twice"


def test_a_concurrent_flush_never_emits_the_same_fragment_twice(merging):
    buffer, emitted = make_buffer()
    buffer.add("the only fragment", 1.0, 2.0)
    start_line = threading.Barrier(6)

    def flusher():
        start_line.wait()
        buffer.flush()

    threads = [threading.Thread(target=flusher) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert emitted.texts == ["the only fragment"]


# --- the watchdog thread ---

def test_watch_returns_a_running_daemon_thread_that_stops_with_the_event(merging):
    buffer, _emitted = make_buffer()
    stop_event = threading.Event()

    thread = buffer.watch(stop_event)
    try:
        assert thread.daemon is True
        assert thread.is_alive()
    finally:
        stop_event.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_the_watchdog_releases_a_held_fragment_on_its_own(merging, monkeypatch):
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 0.0)
    released = threading.Event()
    seen = []

    def emit(text, start, end):
        seen.append((text, start, end))
        released.set()

    buffer = SentenceBuffer(emit)
    stop_event = threading.Event()
    thread = buffer.watch(stop_event)
    try:
        buffer.add("the speaker just stopped", 1.0, 2.0)
        assert released.wait(timeout=5), "held text never reached the screen"
    finally:
        stop_event.set()
        thread.join(timeout=5)

    assert seen == [("the speaker just stopped", 1.0, 2.0)]


def test_an_exception_inside_emit_does_not_kill_the_watchdog(merging, monkeypatch):
    # emit does the translation, which can fail on a network blip. If that
    # killed the watchdog, every later pause would hang on screen forever.
    monkeypatch.setattr(config, "MAX_HOLD_SECONDS", 0.0)
    exploded = threading.Event()
    recovered = threading.Event()
    state = {"raise": True}
    seen = []

    def emit(text, start, end):
        if state["raise"]:
            exploded.set()
            raise RuntimeError("translation backend unreachable")
        seen.append((text, start, end))
        recovered.set()

    buffer = SentenceBuffer(emit)
    stop_event = threading.Event()
    thread = buffer.watch(stop_event)
    try:
        buffer.add("first held fragment", 1.0, 2.0)
        assert exploded.wait(timeout=5)

        assert thread.is_alive(), "the watchdog died on a failing emit"

        state["raise"] = False
        buffer.add("second held fragment", 3.0, 4.0)
        assert recovered.wait(timeout=5), "the watchdog stopped flushing"
    finally:
        stop_event.set()
        thread.join(timeout=5)

    assert seen == [("second held fragment", 3.0, 4.0)]
