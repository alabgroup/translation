"""Small parsers shared by the transcript and eval tests."""

import json


def parse_srt(path):
    """Parse an .srt file into a list of (index, start, end, text) tuples."""
    cues = []
    for block in path.read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.splitlines()
        index = int(lines[0])
        start, _arrow, end = lines[1].partition(" --> ")
        cues.append((index, start.strip(), end.strip(), "\n".join(lines[2:])))
    return cues


def srt_seconds(stamp):
    """Convert an SRT timestamp back to seconds, for ordering assertions."""
    clock, _comma, millis = stamp.partition(",")
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return hours * 3600 + minutes * 60 + seconds + int(millis) / 1000.0


def read_jsonl(path):
    """Parse a .jsonl file into a list of records."""
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
