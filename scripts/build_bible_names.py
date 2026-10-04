#!/usr/bin/env python3
"""Extract biblical proper nouns from the World English Bible.

The WEB is public domain, and proper-noun spellings barely differ between
modern translations, so this list serves equally well for a congregation
reading ESV or NIV - neither of which can be redistributed.

    python scripts/build_bible_names.py /tmp/web

Writes app/data/bible_names.txt.
"""

import re
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "bible_names.txt"

# Capitalised mid-sentence but not names: pronouns, titles and sentence
# connectives the text capitalises for reverence or grammar.
NOT_NAMES = {
    "I", "O", "He", "His", "Him", "Himself", "She", "Her", "They", "Them",
    "You", "Your", "Yours", "We", "Our", "Us", "My", "Mine", "It", "Its",
    "The", "A", "An", "And", "But", "For", "So", "Then", "When", "Where",
    "Who", "Whom", "Whose", "What", "Why", "How", "If", "Yet", "Now",
    "Behold", "Selah", "Amen", "Yes", "No", "Let", "Let's", "Don't",
    "Chapter", "Psalm", "Verse", "Book", "God", "Lord", "LORD", "Father",
    "Son", "Spirit", "King", "Queen", "Prince", "Priest", "Prophet",
}

BOOKS = """Genesis Exodus Leviticus Numbers Deuteronomy Joshua Judges Ruth
Samuel Kings Chronicles Ezra Nehemiah Esther Job Psalms Proverbs
Ecclesiastes Isaiah Jeremiah Lamentations Ezekiel Daniel Hosea Joel Amos
Obadiah Jonah Micah Nahum Habakkuk Zephaniah Haggai Zechariah Malachi
Matthew Mark Luke John Acts Romans Corinthians Galatians Ephesians
Philippians Colossians Thessalonians Timothy Titus Philemon Hebrews James
Peter Jude Revelation""".split()


def extract(source_dir):
    """Count how often each word appears capitalised mid-sentence, and lowercase.

    The lowercase count is the useful signal. A proper noun is essentially
    never written lowercase, while the words verse lines capitalise for poetry
    - Therefore, Because, Those - appear lowercase constantly. That separates
    them far better than a dictionary, which lists "israel" and "jesus" as
    words like any other.
    """
    capitalised, lowercase = Counter(), Counter()
    files = sorted(Path(source_dir).glob("*_read.txt"))
    if not files:
        sys.exit(f"No chapter files in {source_dir}")

    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for word in re.findall(r"\b[a-z][a-zA-Z'\-]+", text):
            lowercase[word.lower()] += 1
        for sentence in re.split(r"[.!?;:]\s+|\n", text):
            words = re.findall(r"[A-Z][a-zA-Z'\-]+", sentence)
            # Skip the first word: capitalisation there says nothing.
            for word in words[1:]:
                if word in NOT_NAMES or len(word) < 3:
                    continue
                capitalised[word] += 1
    return capitalised, lowercase, len(files)


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else "/tmp/web"
    counts, lowercase, file_count = extract(source)

    # A real name recurs, and is rarely if ever written lowercase.
    names = {
        word for word, n in counts.items()
        if n >= 3 and lowercase[word.lower()] <= n * 0.05
    }
    names.update(BOOKS)
    names = sorted(names)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(names) + "\n", encoding="utf-8")

    print(f"chapters read : {file_count}")
    print(f"distinct words: {len(counts)}")
    print(f"names kept    : {len(names)}  -> {OUT.relative_to(OUT.parent.parent.parent)}")
    print("\nmost frequent:")
    for word, n in counts.most_common(15):
        if word in names:
            print(f"  {n:6}  {word}")


if __name__ == "__main__":
    main()
