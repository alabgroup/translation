"""Correct misheard biblical proper nouns.

Whisper mishears names it rarely encounters - "Colossians" as "Colassians",
"Habakkuk" as "Habakuk". The names themselves are stable across translations,
so a list drawn from the public-domain World English Bible corrects a reading
from any translation.

The rule is deliberately narrow: only a word Whisper itself capitalised
mid-sentence is considered, and only when it is not an ordinary English word.
Whisper capitalising a word is its own signal that it believes the word is a
name, so this never reaches into ordinary speech - "mary" the verb is left
alone while "Mary" is checked.
"""

import difflib
import re
from functools import lru_cache
from pathlib import Path

import config

NAMES_FILE = Path(__file__).resolve().parent / "data" / "bible_names.txt"
SYSTEM_WORDS = Path("/usr/share/dict/words")


@lru_cache(maxsize=1)
def _names():
    """Known biblical names, and a lowercase index for matching."""
    if not NAMES_FILE.exists():
        return (), {}
    names = tuple(line.strip() for line in
                  NAMES_FILE.read_text(encoding="utf-8").splitlines() if line.strip())
    return names, {name.lower(): name for name in names}


@lru_cache(maxsize=1)
def _english_words():
    """Ordinary English words, so real words are never 'corrected'."""
    if not SYSTEM_WORDS.exists():
        return frozenset()
    return frozenset(
        line.strip().lower()
        for line in SYSTEM_WORDS.read_text(encoding="utf-8", errors="ignore").splitlines()
        if line.strip()
    )


def _match(word):
    """Closest known name for a word, or None if nothing is close enough."""
    names, by_lower = _names()
    if not names:
        return None

    lowered = word.lower()
    if lowered in by_lower:
        return None                       # already correct
    if lowered in _english_words():
        return None                       # an ordinary word, leave it alone

    close = difflib.get_close_matches(
        lowered, by_lower.keys(), n=1, cutoff=config.NAME_MATCH_CUTOFF)
    if not close:
        return None
    return by_lower[close[0]]


def fix_names(text):
    """Return the text with misheard biblical names corrected.

    Sentence-initial words are checked too. Their capitalisation says nothing,
    but the ordinary-English filter already excludes the words that actually
    start sentences, and the match threshold is strict enough that modern
    names - Janet, Mitchell, Alabaster - find no biblical neighbour.
    """
    if not config.CORRECT_BIBLE_NAMES or not text:
        return text

    pieces = []
    for token in re.split(r"(\W+)", text):
        if token and token[0].isupper() and token.isalpha() and len(token) > 3:
            pieces.append(_match(token) or token)
        else:
            pieces.append(token)
    return "".join(pieces)
