"""The files add_line writes: per-language .srt and .txt, plus transcript.jsonl."""

import pytest

import config
from tests.helpers import parse_srt, read_jsonl, srt_seconds


UTTERANCES = [
    ("Let us pray.", {"Spanish": "Oremos.", "Chinese": "我们祈祷吧。"}, 0.0, 2.0),
    ("Amen.", {"Spanish": "Amén.", "Chinese": "阿门。"}, 2.5, 3.25),
    ("Please be seated.", {"Spanish": "Por favor siéntense.", "Chinese": "请坐下。"}, 4.0, 6.5),
]


@pytest.fixture
def written(transcript, output_dir):
    for source, translations, start, end in UTTERANCES:
        transcript.add_line(source, translations, start, end)
    return output_dir


def test_add_line_writes_an_srt_and_a_txt_for_the_source_and_each_target_language(written):
    for name in (config.SOURCE_LANG, "Spanish", "Chinese"):
        assert (written / f"{name}.srt").exists(), f"missing {name}.srt"
        assert (written / f"{name}.txt").exists(), f"missing {name}.txt"
    assert (written / "transcript.jsonl").exists()


def test_each_languages_srt_numbering_is_its_own_clean_sequence_from_one(written):
    for name in (config.SOURCE_LANG, "Spanish", "Chinese"):
        indexes = [cue[0] for cue in parse_srt(written / f"{name}.srt")]
        assert indexes == [1, 2, 3], f"{name}.srt numbering is {indexes}"


def test_the_same_cue_number_covers_the_same_span_in_every_language(written):
    source_cues = parse_srt(written / f"{config.SOURCE_LANG}.srt")
    for name in ("Spanish", "Chinese"):
        for source_cue, translated_cue in zip(source_cues, parse_srt(written / f"{name}.srt")):
            assert source_cue[:3] == translated_cue[:3]


def test_srt_text_is_the_translation_for_that_language_not_the_source(written):
    spanish = [cue[3] for cue in parse_srt(written / "Spanish.srt")]
    assert spanish == [line[1]["Spanish"] for line in UTTERANCES]


def test_txt_holds_one_utterance_per_line_in_spoken_order(written):
    source_lines = (written / f"{config.SOURCE_LANG}.txt").read_text(encoding="utf-8").splitlines()
    assert source_lines == [line[0] for line in UTTERANCES]

    spanish_lines = (written / "Spanish.txt").read_text(encoding="utf-8").splitlines()
    assert spanish_lines == [line[1]["Spanish"] for line in UTTERANCES]


def test_txt_collapses_an_embedded_newline_so_one_utterance_stays_one_line(transcript, output_dir):
    transcript.add_line("first half\nsecond half", {}, 0.0, 1.0)

    lines = (output_dir / f"{config.SOURCE_LANG}.txt").read_text(encoding="utf-8").splitlines()
    assert lines == ["first half second half"]


def test_jsonl_records_parse_and_carry_source_translations_and_timings(written):
    records = read_jsonl(written / "transcript.jsonl")
    assert len(records) == len(UTTERANCES)

    for record, (source, translations, _start, _end) in zip(records, UTTERANCES):
        assert set(record) >= {"index", "start", "end", "duration", "source", "translations"}
        assert record["source"] == source
        assert record["translations"] == translations
        assert record["duration"] == pytest.approx(record["end"] - record["start"], abs=1e-6)
        assert record["end"] > record["start"]


def test_jsonl_index_matches_the_srt_cue_number_for_the_same_utterance(written):
    records = read_jsonl(written / "transcript.jsonl")
    cues = parse_srt(written / f"{config.SOURCE_LANG}.srt")
    assert [record["index"] for record in records] == [cue[0] for cue in cues]


def test_jsonl_timings_match_the_srt_timestamps_after_overlap_correction(written):
    records = read_jsonl(written / "transcript.jsonl")
    cues = parse_srt(written / f"{config.SOURCE_LANG}.srt")
    for record, cue in zip(records, cues):
        assert record["start"] == pytest.approx(srt_seconds(cue[1]), abs=0.001)
        assert record["end"] == pytest.approx(srt_seconds(cue[2]), abs=0.001)


def test_jsonl_records_non_ascii_translations_as_readable_text_not_escapes(written):
    raw = (written / "transcript.jsonl").read_text(encoding="utf-8")
    assert "Amén." in raw
    assert "\\u00e9" not in raw


def test_the_output_directory_is_created_even_when_its_parent_does_not_exist(
        transcript, tmp_path, monkeypatch):
    # Regression: mkdir() without parents=True raised FileNotFoundError on the
    # first utterance of a run whose output/ root had never been created.
    nested = tmp_path / "output" / "20260913-120000"
    monkeypatch.setattr(transcript, "OUTPUT_DIR", nested)
    assert not nested.parent.exists()

    transcript.add_line("first words of the run", {"Spanish": "primeras palabras"}, 0.0, 1.0)

    assert nested.is_dir()
    assert (nested / "transcript.jsonl").exists()


def test_nothing_is_written_when_srt_output_is_switched_off(transcript, output_dir, monkeypatch):
    monkeypatch.setattr(config, "WRITE_SRT", False)

    transcript.add_line("not persisted", {"Spanish": "no guardado"}, 0.0, 1.0)

    assert not output_dir.exists()
    revision, lines, _active = transcript.snapshot()
    assert revision == 1 and len(lines) == 1


def test_snapshot_returns_the_appended_lines_and_a_revision_that_advances(transcript):
    before, _lines, _active = transcript.snapshot()
    transcript.add_line("hello", {"Spanish": "hola"}, 0.0, 1.0)
    after, lines, active = transcript.snapshot()

    assert after > before
    assert lines[-1]["source"] == "hello"
    assert lines[-1]["translations"] == {"Spanish": "hola"}
    assert active in transcript.languages()


def test_only_the_most_recent_lines_are_kept_in_memory(transcript):
    for index in range(transcript.MAX_LINES + 10):
        transcript.add_line(f"line {index}", {}, index, index + 0.5)

    _revision, lines, _active = transcript.snapshot()
    assert len(lines) == transcript.MAX_LINES
    assert lines[-1]["source"] == f"line {transcript.MAX_LINES + 9}"


def test_set_active_language_rejects_a_language_that_is_not_configured(transcript):
    with pytest.raises(ValueError):
        transcript.set_active_language("Klingon")


def test_set_active_language_switches_the_overlay_and_bumps_the_revision(transcript):
    before, _lines, _active = transcript.snapshot()

    transcript.set_active_language("Source")

    revision, _lines, active = transcript.snapshot()
    assert active == "Source"
    assert revision > before
