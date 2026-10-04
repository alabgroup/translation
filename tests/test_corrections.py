"""Biblical name correction.

The risk here is over-correction: a layer that rewrites ordinary speech is
far worse than one that misses a misheard name. Most of these tests assert
that nothing changes.
"""

import pytest

import config
from app.corrections import _match, fix_names


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(config, "CORRECT_BIBLE_NAMES", True)
    monkeypatch.setattr(config, "NAME_MATCH_CUTOFF", 0.84)


# --- Corrections that should happen ---

@pytest.mark.parametrize("misheard, expected", [
    ("Colassians", "Colossians"),
    ("Habakuk", "Habakkuk"),
    ("Thessalonions", "Thessalonians"),
    ("Deuteronamy", "Deuteronomy"),
    ("Melchizadek", "Melchizedek"),
    ("Nebuchadnezer", "Nebuchadnezzar"),
])
def test_a_misheard_book_or_figure_is_corrected(misheard, expected):
    assert _match(misheard) == expected


def test_a_misheard_name_is_corrected_inside_a_sentence():
    assert fix_names("Turn to Colassians chapter three.") == \
        "Turn to Colossians chapter three."


def test_a_misheard_name_is_corrected_at_the_start_of_a_sentence():
    # Capitalisation says nothing sentence-initially, so this relies entirely
    # on the word being unlike any ordinary English word.
    assert fix_names("Nebuchadnezer built it.") == "Nebuchadnezzar built it."


def test_several_names_in_one_sentence_are_all_corrected():
    assert fix_names("Paul wrote to the Ephesisans and the Philipians.") == \
        "Paul wrote to the Ephesians and the Philippians."


def test_surrounding_punctuation_and_spacing_are_preserved():
    assert fix_names("  (Colassians, three)  ") == "  (Colossians, three)  "


# --- Corrections that must NOT happen ---

@pytest.mark.parametrize("modern", [
    "Janet", "Mitchell", "Tyler", "Brandon", "Kayla",
    "Alabaster", "Sydney", "Newport", "Google",
])
def test_a_modern_name_is_never_snapped_to_a_biblical_one(modern):
    assert _match(modern) is None


@pytest.mark.parametrize("sentence", [
    "Please stand and open your bulletin.",
    "Yesterday we talked about forgiveness.",
    "I want to marry those two ideas together.",
    "The offering will be collected shortly.",
    "Welcome, everyone, to our morning service.",
])
def test_ordinary_speech_is_left_alone(sentence):
    assert fix_names(sentence) == sentence


@pytest.mark.parametrize("sentence", [
    "David defeated Goliath in the valley.",
    "Mary and Martha went to see Lazarus.",
    "We read in Matthew and Luke about Jesus.",
])
def test_names_that_are_already_correct_are_untouched(sentence):
    assert fix_names(sentence) == sentence


def test_a_lowercase_word_is_never_corrected():
    # Whisper capitalising a word is the signal that it means a name.
    assert fix_names("he went to colassians") == "he went to colassians"


def test_short_words_are_not_corrected():
    # Three letters or fewer match too many names to be safe.
    assert fix_names("The Ark was built.") == "The Ark was built."


# --- Switches and edges ---

def test_the_layer_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(config, "CORRECT_BIBLE_NAMES", False)
    assert fix_names("Turn to Colassians.") == "Turn to Colassians."


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_empty_input_is_returned_unchanged(text):
    assert fix_names(text) == text


def test_a_stricter_cutoff_corrects_less(monkeypatch):
    monkeypatch.setattr(config, "NAME_MATCH_CUTOFF", 0.99)
    _match.cache_clear() if hasattr(_match, "cache_clear") else None
    assert fix_names("Turn to Colassians.") == "Turn to Colassians."
