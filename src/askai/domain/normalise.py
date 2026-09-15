"""The single fold applied to every text the engine compares.

Purity: pure, imports nothing in-project.

An index and a query that fold text differently cannot meet. That is not a
hypothetical: it is finding 121's Arabic half, where a reviewed frame word could
never match because the query had already been folded to a different spelling by
the time the comparison ran. The tree being replaced carries three copies of this
function, and two of their own docstrings warn that a third spelling would
reintroduce exactly that defect.

So there is **exactly one** ``normalise()``, it lives here, and it takes no
configuration and has no variants -- a per-call-site option is a second
normalisation wearing one name. Index build, query, lexical match and alias
lookup all call this. ``tests/test_normalise.py`` asserts there is no second
implementation and that every call site resolves to this same function object.

The fold, in order:

1. **NFKC**, so a compatibility spelling (presentation forms, full-width Latin,
   ligatures) is the same text as the ordinary one.
2. **Case fold**, which is what the measured predecessors did and what makes an
   English name usable as a lookup key.
3. **Drop nonspacing marks.** Arabic harakat stand alone after NFKC -- the script
   has no precomposed vowelled forms -- so removing them here removes the
   diacritics without touching a letter.
4. **Drop tatweel.** It is a justification stretch, not a letter, but it is
   classified as a modifier letter and so survives step 3.
5. **Fold the interchangeable letter forms**: alef with hamza above, below and
   madda to plain alef; alef maksura to yeh; teh marbuta to heh. A reader types
   either spelling without thinking about it, so folding them is undoing an
   orthographic choice, not guessing at meaning.
6. **Strip Latin accents**, in a pass restricted to the Latin combining block.
   This is deliberately *not* done by decomposing the whole string: NFD would
   also split the hamza off waw and yeh, folding two letters this list does not
   name and the predecessors kept apart.
7. **Collapse punctuation and whitespace** -- every run of characters that is
   neither a letter nor a digit becomes a single space, and the ends are
   stripped.

Step 7 collapses to a space rather than to nothing on purpose: deleting the
separator would fuse two words into one token, so a hyphenated name and its
spaced spelling must meet in the middle rather than at either extreme.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

__all__ = ["normalise"]

# U+0640 ARABIC TATWEEL. Category Lm, so step 3 leaves it behind.
_TATWEEL: Final = "ـ"

# Written as escapes with the Unicode names in the comment rather than as literal
# Arabic characters: a bidirectional run inside a source line reorders on screen,
# and a mapping whose visual order differs from its logical order is a mapping no
# reviewer can check.
_LETTER_FOLDS: Final = str.maketrans(
    {
        "أ": "ا",  # ALEF WITH HAMZA ABOVE -> ALEF
        "إ": "ا",  # ALEF WITH HAMZA BELOW -> ALEF
        "آ": "ا",  # ALEF WITH MADDA ABOVE -> ALEF
        "ى": "ي",  # ALEF MAKSURA -> YEH
        "ة": "ه",  # TEH MARBUTA -> HEH
    }
)

# The Latin combining diacritics only. Stripping every nonspacing mark from a
# *decomposed* string would reach the hamza carriers, which step 5 does not name.
_LATIN_MARKS_FIRST: Final = 0x0300
_LATIN_MARKS_LAST: Final = 0x036F

# `\W` is Unicode-aware here and already includes whitespace, so one substitution
# does both collapses and a run mixing the two cannot survive as two spaces.
# `_` is added because `\w` counts it as a word character and it is punctuation.
_SEPARATORS: Final = re.compile(r"[\W_]+")


def _without_latin_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    kept = "".join(
        character
        for character in decomposed
        if not (_LATIN_MARKS_FIRST <= ord(character) <= _LATIN_MARKS_LAST)
    )
    # Recompose, so a character this pass did not touch comes back in the form the
    # rest of the system stores it in.
    return unicodedata.normalize("NFC", kept)


def normalise(raw: str) -> str:
    """The normal form of *raw*: the only one, used by every path comparing text.

    Two strings that differ only by compatibility spelling, case, diacritics,
    tatweel, hamza form, final yeh or teh marbuta spelling, punctuation or
    whitespace normalise to the same string.
    """
    compatible = unicodedata.normalize("NFKC", raw).casefold()
    without_marks = "".join(
        character for character in compatible if unicodedata.category(character) != "Mn"
    )
    folded = without_marks.replace(_TATWEEL, "").translate(_LETTER_FOLDS)
    return _SEPARATORS.sub(" ", _without_latin_accents(folded)).strip()
