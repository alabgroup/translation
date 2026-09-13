"""Word-level edit counting (eval.py).

The WER report is only meaningful if substitutions, deletions and insertions
are told apart: deletions point at segmentation settings, insertions at
hallucinated filler. Every case below is hand-checked.
"""

import importlib

import pytest


evaluation = importlib.import_module("eval")
edit_counts = evaluation.edit_counts


def errors(counts):
    return counts["s"] + counts["d"] + counts["i"]


REFERENCE = "let us pray for the people of this city".split()


# --- no errors ---

def test_identical_sequences_report_no_errors():
    counts = edit_counts(REFERENCE, list(REFERENCE))

    assert counts == {"s": 0, "d": 0, "i": 0, "=": len(REFERENCE)}


def test_two_empty_sequences_report_no_errors():
    assert edit_counts([], []) == {"s": 0, "d": 0, "i": 0, "=": 0}


# --- one error of each kind, never confused with another ---

def test_one_substitution_is_counted_as_a_substitution_only():
    hypothesis = "let us pray for the people of this town".split()

    counts = edit_counts(REFERENCE, hypothesis)

    assert counts["s"] == 1
    assert counts["d"] == 0
    assert counts["i"] == 0
    assert counts["="] == len(REFERENCE) - 1


def test_one_deletion_is_counted_as_a_deletion_only():
    # "the" was said but never transcribed.
    hypothesis = "let us pray for people of this city".split()

    counts = edit_counts(REFERENCE, hypothesis)

    assert counts["d"] == 1
    assert counts["s"] == 0
    assert counts["i"] == 0
    assert counts["="] == len(hypothesis)


def test_one_insertion_is_counted_as_an_insertion_only():
    # "now" was transcribed but never said.
    hypothesis = "let us pray now for the people of this city".split()

    counts = edit_counts(REFERENCE, hypothesis)

    assert counts["i"] == 1
    assert counts["s"] == 0
    assert counts["d"] == 0
    assert counts["="] == len(REFERENCE)


def test_a_substitution_is_not_reported_as_a_deletion_plus_an_insertion():
    counts = edit_counts(["amen"], ["ramen"])

    assert counts == {"s": 1, "d": 0, "i": 0, "=": 0}
    assert errors(counts) == 1


def test_a_deletion_and_an_insertion_are_not_collapsed_into_a_substitution():
    reference = "let us all pray".split()
    hypothesis = "let us pray now".split()   # "all" missing, "now" added

    counts = edit_counts(reference, hypothesis)

    assert counts["d"] == 1
    assert counts["i"] == 1
    assert counts["s"] == 0
    assert counts["="] == 3


# --- degenerate sequences ---

def test_an_empty_hypothesis_against_a_reference_is_all_deletions():
    counts = edit_counts(REFERENCE, [])

    assert counts == {"s": 0, "d": len(REFERENCE), "i": 0, "=": 0}
    assert errors(counts) == len(REFERENCE)


def test_an_empty_reference_against_a_hypothesis_is_all_insertions():
    hypothesis = "thank you for watching".split()

    counts = edit_counts([], hypothesis)

    assert counts == {"s": 0, "d": 0, "i": len(hypothesis), "=": 0}


def test_two_sequences_with_nothing_in_common_cost_the_longer_length():
    counts = edit_counts(["alpha", "bravo"], ["charlie", "delta", "echo"])

    assert errors(counts) == 3
    assert counts["="] == 0


# --- the counts add up ---

@pytest.mark.parametrize("reference,hypothesis", [
    ("let us pray", "let us pray"),
    ("let us pray", "let us pray now"),
    ("let us pray", "us pray"),
    ("let us pray", "let we pray"),
    ("", "thank you"),
    ("amen amen amen", "amen"),
    ("the lord be with you", "and also with you"),
])
def test_matches_plus_substitutions_and_deletions_account_for_every_reference_word(
        reference, hypothesis):
    reference_words, hypothesis_words = reference.split(), hypothesis.split()

    counts = edit_counts(reference_words, hypothesis_words)

    assert counts["="] + counts["s"] + counts["d"] == len(reference_words)
    assert counts["="] + counts["s"] + counts["i"] == len(hypothesis_words)


def test_the_error_total_equals_the_levenshtein_distance():
    # "the lord be with you" -> "and also with you": 3 edits by hand
    # (the->and, lord->also, be deleted).
    counts = edit_counts("the lord be with you".split(), "and also with you".split())

    assert errors(counts) == 3


def test_normalise_lowercases_and_strips_punctuation_before_scoring():
    assert evaluation.normalise("Let us pray, and say: “Amen!”") == "let us pray and say amen"


def test_normalise_keeps_apostrophes_and_folds_the_typographic_one():
    assert evaluation.normalise("Lord’s  Prayer") == "lord's prayer"


def test_a_run_scores_zero_word_error_rate_against_itself():
    words = evaluation.normalise("Let us pray for the people of this city.").split()

    counts = edit_counts(words, list(words))

    assert errors(counts) / max(len(words), 1) == 0.0
