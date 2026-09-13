# Tests

Regression tests for the live translation pipeline. They are fast (well under a
second), fully offline, and safe to run while a service is on air.

## Running them

```sh
.venv/bin/python -m pytest -q            # whole suite
.venv/bin/python -m pytest -q tests/test_transcript_timestamps.py
.venv/bin/python -m pytest -q -k hallucination
.venv/bin/python -m pytest -rA           # show every test name
```

`pytest` is the only test dependency. If it is missing:

```sh
.venv/bin/pip install pytest
```

`pytest.ini` at the repo root puts the repo on `sys.path`, so the tests import
`config`, `eval` and `app.*` exactly the way the application does. Run pytest
from the repo root.

## Safety rules the suite keeps

* **Nothing is written into `output/`.** Every test that exercises transcript
  files redirects `transcript.OUTPUT_DIR` at pytest's `tmp_path`.
* **The Whisper model is never loaded and nothing is downloaded.** The
  hallucination tests replace `transcribe.load_model` with a stub that fails
  the test if it is called, and assert afterwards that no model was built.
* **No audio device is opened.** `sounddevice.query_devices` is replaced with a
  fixed device table; no stream is ever constructed.
* **No socket is bound.** The HTTP tests go through Flask's `test_client`, so a
  pipeline already serving on port 8000 is untouched.
* **Module-level state is restored.** `app.transcript`, `app.audio` and
  `config` all hold mutable globals; every fixture uses `monkeypatch.setattr`,
  which puts the original value back when the test ends.

## What each module covers

| File | Covers |
| --- | --- |
| `conftest.py` | Fixtures: `transcript` (fresh globals + throwaway `OUTPUT_DIR`), `output_dir`, `restore_config`. |
| `helpers.py` | `.srt` and `.jsonl` parsers used by the assertions. |
| `test_transcript_timestamps.py` | `_srt_timestamp`: negative seconds clamp to `00:00:00,000`; millisecond rounding carries instead of emitting `,1000`; zero-padded field widths. Cue ordering across successive `add_line` calls: never overlapping, never backwards, never zero-length, even when a later call passes a start behind the previous end. |
| `test_transcript_output.py` | The files `add_line` writes: `<language>.srt`, `<language>.txt`, `transcript.jsonl`. Per-language cue numbering is its own clean `1,2,3`; the same cue number covers the same span in every language; `.txt` holds one utterance per line; JSONL records parse and carry `source`, `translations`, `start`, `end`, `duration`, with timings matching the `.srt`. Also: the output directory is created when its parent does not exist, `WRITE_SRT = False` writes nothing, and the in-memory line buffer is capped. |
| `test_transcribe_hallucination.py` | `_is_hallucination`: stock phrases (`"Thank you."`, `"You"`, `"you."`, `"Thanks for watching!"`, `"okay"`) are dropped as whole utterances; real speech containing them (`"Amen."`, `"Let us pray."`, `"Thank you for coming today."`, `"Okay, please stand."`) is kept. Case-insensitivity, trailing punctuation and whitespace. Plus `transcribe()` segment filtering against a stubbed model. |
| `test_settings_validation.py` | `settings.update`: out-of-range values rejected, unknown keys rejected, non-numeric input rejected, whole-number-step settings coerced to `int`, fractional-step settings keeping their decimals, valid updates written through to `config`. `snapshot()` and `values()` shapes. |
| `test_audio_devices.py` | `_resolve_device`: `None` and `int` pass through unchanged, a partial name resolves case-insensitively to the right index, no match raises `ValueError` naming the available devices. `list_devices` excludes output-only devices and keeps each device's real table index. Plus `describe_device`, `set_device` validation and mute round-tripping. |
| `test_server_api.py` | `/health` and `/api/lines` response keys; `/api/lines` preserving the configured language order rather than sorting alphabetically; `POST /api/active` accepting configured languages and rejecting unknown ones with 400; `POST /api/settings` rejecting out-of-range values and untunable keys with 400; `/display/<unknown>` returning 404; `/api/audio` shape. |
| `test_eval_edit_counts.py` | `eval.edit_counts` against hand-checked cases: identical sequences score zero; one substitution, one deletion and one insertion are each counted correctly and never confused with one another; an empty hypothesis is all deletions; the counts reconcile with both sequence lengths. Plus `normalise`. |

## Known defects

Three tests are marked `xfail(strict=True)`. They assert the behaviour the code
*should* have, and they document a real defect rather than fixing it. Because
they are strict, they fail as soon as the defect is fixed — that is the signal
to delete the marker, not the test.

1. `settings.update()` applies changes one key at a time, so a batch containing
   an invalid value raises `ValueError` (and `POST /api/settings` answers 400)
   *after* the valid keys ahead of it have already been written to `config`.
2. `/display/<language>` matches a language name case-insensitively, but
   `POST /api/active` requires an exact-case match, so `"spanish"` is a working
   overlay URL and a 400 on the API.
