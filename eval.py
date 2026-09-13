#!/usr/bin/env python3
"""Measure how much accuracy the live pipeline gives up for speed.

Re-transcribes a run's recorded audio with a larger Whisper model and
compares it against what the live pipeline produced.

IMPORTANT: the larger model is a proxy reference, not ground truth. This
measures "how much worse is the live model than a bigger one", which is the
question that decides whether to change WHISPER_MODEL. Absolute accuracy
needs a human transcript.

Usage:
    python eval.py                      # newest run in output/
    python eval.py output/20260913-112814
    python eval.py --model medium       # cheaper reference
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"


def newest_run():
    runs = [p for p in OUTPUT_ROOT.glob("*") if (p / "transcript.jsonl").exists()]
    if not runs:
        sys.exit(f"No runs with a transcript found in {OUTPUT_ROOT}")
    return max(runs, key=lambda p: p.stat().st_mtime)


def normalise(text):
    """Lowercase, strip punctuation, collapse whitespace - standard for WER."""
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^\w\s']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def edit_counts(reference, hypothesis):
    """Levenshtein over word lists, returning (substitutions, deletions, insertions)."""
    rows, cols = len(reference) + 1, len(hypothesis) + 1
    dist = [[0] * cols for _ in range(rows)]
    back = [[None] * cols for _ in range(rows)]

    for i in range(rows):
        dist[i][0] = i
        back[i][0] = "d"
    for j in range(cols):
        dist[0][j] = j
        back[0][j] = "i"
    back[0][0] = None

    for i in range(1, rows):
        for j in range(1, cols):
            if reference[i - 1] == hypothesis[j - 1]:
                dist[i][j], back[i][j] = dist[i - 1][j - 1], "="
                continue
            choices = ((dist[i - 1][j - 1] + 1, "s"),
                       (dist[i - 1][j] + 1, "d"),
                       (dist[i][j - 1] + 1, "i"))
            dist[i][j], back[i][j] = min(choices)

    counts = {"s": 0, "d": 0, "i": 0, "=": 0}
    i, j = len(reference), len(hypothesis)
    while i > 0 or j > 0:
        op = back[i][j]
        counts[op] += 1
        if op in ("=", "s"):
            i, j = i - 1, j - 1
        elif op == "d":
            i -= 1
        else:
            j -= 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", nargs="?", help="Run directory (default: newest)")
    parser.add_argument("--model", default="large-v3",
                        help="Reference model: medium, large-v3 (default large-v3)")
    parser.add_argument("--save", action="store_true",
                        help="Write the reference transcript next to the run")
    args = parser.parse_args()

    run = Path(args.run) if args.run else newest_run()
    audio_path = run / "audio.wav"
    jsonl_path = run / "transcript.jsonl"

    if not jsonl_path.exists():
        sys.exit(f"No transcript.jsonl in {run}")
    if not audio_path.exists():
        sys.exit(f"No audio.wav in {run}.\n"
                 f"Set RECORD_AUDIO = True in config.py and record a run first.")

    records = [json.loads(line) for line in jsonl_path.read_text().splitlines() if line.strip()]
    live_text = " ".join(r["source"] for r in records)
    print(f"Run:        {run.name}")
    print(f"Utterances: {len(records)}")
    print(f"Reference:  whisper {args.model} (proxy, not ground truth)")
    print("\nTranscribing reference — this is slower than real time, please wait…\n")

    from faster_whisper import WhisperModel
    model = WhisperModel(args.model, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(audio_path), language="en",
                                       vad_filter=True, beam_size=5)
    reference_text = " ".join(s.text.strip() for s in segments).strip()

    if args.save:
        (run / f"reference-{args.model}.txt").write_text(reference_text + "\n")

    ref_words = normalise(reference_text).split()
    hyp_words = normalise(live_text).split()
    counts = edit_counts(ref_words, hyp_words)
    errors = counts["s"] + counts["d"] + counts["i"]
    wer = errors / max(len(ref_words), 1)

    print(f"reference words : {len(ref_words)}")
    print(f"live words      : {len(hyp_words)}")
    print(f"  substitutions : {counts['s']}")
    print(f"  deletions     : {counts['d']}   (said but not transcribed)")
    print(f"  insertions    : {counts['i']}   (transcribed but not said)")
    print(f"\nWER vs {args.model}: {wer:.1%}   →  {1 - wer:.1%} agreement")
    print("\nDeletions usually mean speech lost to segmentation (silence threshold,")
    print("shortest-phrase setting). Insertions usually mean hallucinated filler.")


if __name__ == "__main__":
    main()
