"""The index's reviewed constants, read from ``rules/`` and never written here.

Purity: reads the packaged rule files (cached by the loader); pure thereafter.

AD-11: a constant a reader can feel lives in a versioned data file, not in code. Three
of the index's do -- the vector width, the character-trigram parameters, and how many
candidates a search hands on -- and this module is the one door to them, so that a
second call site cannot acquire a second opinion about the width of a vector.

The reads are *typed on the way out*. ``RuleSet.value`` returns the union a rule clause
may carry, and an index that silently accepted a string where it wanted an integer would
build vectors of a width nobody chose. A clause of the wrong type stops the process here,
with the rule id in the message, which is where an operator can act on it.
"""

from __future__ import annotations

from typing import Final

from askai.rules import rules

__all__ = [
    "CANDIDATE_LIMIT_RULE",
    "TRIGRAM_RULE",
    "VECTOR_WIDTH_RULE",
    "candidate_limit",
    "pad_boundaries",
    "trigram_size",
    "vector_width",
]

VECTOR_WIDTH_RULE: Final = "R-INDEX-VECTOR-WIDTH"
TRIGRAM_RULE: Final = "R-INDEX-CHARACTER-TRIGRAM-FALLBACK"
CANDIDATE_LIMIT_RULE: Final = "R-INDEX-CANDIDATE-LIMIT"


class TuningError(RuntimeError):
    """A rule clause the index needs is missing or is not the type it must be."""


def _positive_int(rule_id: str, key: str) -> int:
    value = rules().value(rule_id, key)
    # `bool` is an `int` in Python, and `True` as a vector width would be a one-column
    # index that looked like a configuration choice rather than a mistake.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TuningError(f"{rule_id} value `{key}` is {value!r}; the index needs a whole number")
    if value < 1:
        raise TuningError(f"{rule_id} value `{key}` is {value}; it must be at least 1")
    return value


def _flag(rule_id: str, key: str) -> bool:
    value = rules().value(rule_id, key)
    if not isinstance(value, bool):
        raise TuningError(f"{rule_id} value `{key}` is {value!r}; the index needs true or false")
    return value


def vector_width() -> int:
    """How many dimensions every vector in a collection carries."""
    return _positive_int(VECTOR_WIDTH_RULE, "dimensions")


def trigram_size() -> int:
    """The character window the shipped fallback vectoriser cuts text into."""
    return _positive_int(TRIGRAM_RULE, "trigram_size")


def pad_boundaries() -> bool:
    """Whether the fallback pads text so a word's first and last characters count twice.

    Padding is what makes a prefix match score: without it the first two characters of a
    surface appear in no window, and a reader who types the beginning of a name is the
    commonest case there is.
    """
    return _flag(TRIGRAM_RULE, "pad_boundaries")


def candidate_limit() -> int:
    """How many candidates one search over one collection may return (AD-25 stage 1)."""
    return _positive_int(CANDIDATE_LIMIT_RULE, "candidates")
