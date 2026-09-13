"""Hallucination filtering (app/transcribe.py).

Whisper answers silence with stock phrases. Left in, they reset the overlay's
clear timer so subtitles never blank. The filter must be aggressive about those
phrases and completely inert on real speech that happens to contain them - a
service says "Amen." and "Thank you for coming today." constantly.

No test here loads the Whisper model: ``load_model`` is stubbed out so a
regression that made the pure functions touch it would fail loudly.
"""

import types

import pytest

import config
from app import transcribe


@pytest.fixture(autouse=True)
def never_load_the_whisper_model(monkeypatch):
    """Any attempt to load or download the model fails the test immediately."""
    def forbidden():
        raise AssertionError("the tests must never load the Whisper model")

    monkeypatch.setattr(transcribe, "load_model", forbidden)
    yield
    assert transcribe._model is None, "a Whisper model was instantiated"


# --- phrases that must be dropped ---

DROPPED = [
    "Thank you.",
    "You",
    "you.",
    "Thanks for watching!",
    "okay",
    "Thank you",
    "Thanks",
    "Thank you very much.",
    "Thank you for watching.",
    "Please subscribe!",
    "Bye.",
    "Bye bye",
    "The end.",
    "Music",
    "BLANK_AUDIO",
]


@pytest.mark.parametrize("text", DROPPED)
def test_a_stock_phrase_alone_is_treated_as_a_hallucination(text):
    assert transcribe._is_hallucination(text) is True


# --- phrases that must survive ---

KEPT = [
    "Amen.",
    "Let us pray.",
    "Thank you for coming today.",
    "Okay, please stand.",
    "Thank you, Lord.",
    "You are welcome here.",
    "Thanks be to God.",
    "And thank you.",
    "The end of the reading.",
    "Bye for now, everyone.",
]


@pytest.mark.parametrize("text", KEPT)
def test_real_speech_containing_a_stock_phrase_is_not_treated_as_a_hallucination(text):
    assert transcribe._is_hallucination(text) is False


# --- normalisation rules ---

@pytest.mark.parametrize("text", ["thank you", "Thank You", "THANK YOU", "ThAnK yOu"])
def test_matching_ignores_capitalisation(text):
    assert transcribe._is_hallucination(text) is True


@pytest.mark.parametrize("text", ["Thank you.", "Thank you!", "Thank you?", "Thank you,",
                                  "Thank you…", "\"Thank you.\"", "'Thank you'", "Thank you..."])
def test_matching_ignores_surrounding_punctuation_and_quotes(text):
    assert transcribe._is_hallucination(text) is True


@pytest.mark.parametrize("text", ["  Thank you.  ", "\tokay\n", " You "])
def test_matching_ignores_surrounding_whitespace(text):
    assert transcribe._is_hallucination(text) is True


def test_an_empty_utterance_is_not_reported_as_a_hallucination():
    # "" is empty, not a stock phrase; transcribe() drops it on its own path.
    assert transcribe._is_hallucination("") is False


def test_every_configured_phrase_is_dropped_when_spoken_alone():
    for phrase in config.HALLUCINATION_PHRASES:
        assert transcribe._is_hallucination(phrase) is True, phrase
        assert transcribe._is_hallucination(phrase.upper() + ".") is True, phrase


def test_a_stock_phrase_with_any_extra_word_survives():
    for phrase in sorted(config.HALLUCINATION_PHRASES):
        assert transcribe._is_hallucination(f"{phrase} everyone") is False, phrase


# --- transcribe(), with the model stubbed out ---

def _segment(text, no_speech_prob=0.0, avg_logprob=0.0):
    return types.SimpleNamespace(text=text, no_speech_prob=no_speech_prob,
                                 avg_logprob=avg_logprob)


@pytest.fixture
def stub_model(monkeypatch):
    """Replace the Whisper model with one that returns canned segments."""
    def install(segments):
        model = types.SimpleNamespace(
            transcribe=lambda audio, **kwargs: (iter(segments), None))
        monkeypatch.setattr(transcribe, "load_model", lambda: model)
        return model

    return install


def test_transcribe_joins_the_kept_segments_into_one_utterance(stub_model):
    stub_model([_segment(" Let us pray. "), _segment("Amen.")])
    assert transcribe.transcribe(object()) == "Let us pray. Amen."


def test_transcribe_drops_a_segment_whisper_itself_doubts_is_speech(stub_model):
    stub_model([_segment("Let us pray.", no_speech_prob=config.MAX_NO_SPEECH_PROB + 0.1)])
    assert transcribe.transcribe(object()) == ""


def test_transcribe_drops_a_segment_below_the_confidence_floor(stub_model):
    stub_model([_segment("Let us pray.", avg_logprob=config.MIN_AVG_LOGPROB - 0.1)])
    assert transcribe.transcribe(object()) == ""


def test_transcribe_returns_empty_when_the_whole_utterance_is_a_stock_phrase(stub_model):
    stub_model([_segment("Thank you.")])
    assert transcribe.transcribe(object()) == ""


def test_transcribe_keeps_a_stock_phrase_that_is_only_part_of_the_utterance(stub_model):
    stub_model([_segment("Thank you"), _segment("for coming today.")])
    assert transcribe.transcribe(object()) == "Thank you for coming today."
