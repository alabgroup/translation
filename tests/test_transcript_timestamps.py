"""SRT timestamp formatting and cue ordering (app/transcript.py).

These are the regressions that produce .srt files a player silently refuses:
negative timestamps, a millisecond field of 1000, and cues that overlap or
run backwards.
"""

import pytest

from tests.helpers import parse_srt, srt_seconds


# --- _srt_timestamp ---

def test_zero_seconds_formats_as_full_srt_zero_timestamp(transcript):
    assert transcript._srt_timestamp(0) == "00:00:00,000"


@pytest.mark.parametrize("negative", [-0.001, -1.0, -8.394, -3600.0])
def test_negative_seconds_clamp_to_zero_instead_of_emitting_a_negative_clock(transcript, negative):
    # A negative value used to format as "-1:59:52,-394", which no player reads.
    assert transcript._srt_timestamp(negative) == "00:00:00,000"


def test_millisecond_rounding_carries_into_the_next_second(transcript):
    # 1.9999 rounds to 1000 ms; that must become 2 s, 0 ms, never ",1000".
    assert transcript._srt_timestamp(1.9999) == "00:00:02,000"


@pytest.mark.parametrize("seconds", [0.9999, 1.9999, 59.9999, 3599.9996])
def test_millisecond_field_is_never_one_thousand(transcript, seconds):
    stamp = transcript._srt_timestamp(seconds)
    assert not stamp.endswith(",1000"), stamp
    assert int(stamp.rpartition(",")[2]) < 1000


def test_minute_carry_rolls_the_hour_field(transcript):
    assert transcript._srt_timestamp(3599.9999) == "01:00:00,000"


@pytest.mark.parametrize("seconds,expected", [
    (1.5, "00:00:01,500"),
    (61.25, "00:01:01,250"),
    (3661.007, "01:01:01,007"),
    (7325.5, "02:02:05,500"),
])
def test_seconds_format_as_zero_padded_hours_minutes_seconds_millis(transcript, seconds, expected):
    assert transcript._srt_timestamp(seconds) == expected


def test_every_timestamp_field_is_zero_padded_to_a_fixed_width(transcript):
    stamp = transcript._srt_timestamp(5.04)
    assert stamp == "00:00:05,040"
    assert len(stamp) == len("00:00:00,000")


# --- cue ordering across successive add_line calls ---

def test_a_later_cue_starting_before_the_previous_end_is_pushed_to_that_end(transcript, output_dir):
    transcript.add_line("first", {}, 0.0, 5.0)
    transcript.add_line("second", {}, 4.2, 7.0)   # starts 0.8s behind the last end

    cues = parse_srt(output_dir / "en.srt")
    assert srt_seconds(cues[0][2]) == pytest.approx(5.0)
    assert srt_seconds(cues[1][1]) == pytest.approx(5.0)
    assert srt_seconds(cues[1][2]) == pytest.approx(7.0)


def test_cues_never_overlap_or_move_backwards_across_many_add_line_calls(transcript, output_dir):
    # A deliberately hostile sequence: overlapping, backwards and negative spans.
    spans = [(0.0, 2.0), (1.0, 3.0), (0.5, 0.6), (-4.0, -1.0), (2.5, 9.0), (9.0, 9.0)]
    for index, (start, end) in enumerate(spans):
        transcript.add_line(f"line {index}", {}, start, end)

    cues = parse_srt(output_dir / "en.srt")
    assert len(cues) == len(spans)

    previous_end = 0.0
    for _index, start, end, _text in cues:
        start_seconds, end_seconds = srt_seconds(start), srt_seconds(end)
        assert start_seconds >= previous_end, "cue starts before the previous cue ended"
        assert end_seconds > start_seconds, "cue ends at or before it starts"
        previous_end = end_seconds


def test_a_zero_length_span_is_widened_so_the_cue_has_a_visible_duration(transcript, output_dir):
    transcript.add_line("instant", {}, 3.0, 3.0)

    _index, start, end, _text = parse_srt(output_dir / "en.srt")[0]
    assert srt_seconds(end) > srt_seconds(start)


def test_a_fully_negative_span_is_clamped_to_the_start_of_the_timeline(transcript, output_dir):
    transcript.add_line("before the start", {}, -9.0, -2.0)

    _index, start, end, _text = parse_srt(output_dir / "en.srt")[0]
    assert start == "00:00:00,000"
    assert srt_seconds(end) > 0.0
