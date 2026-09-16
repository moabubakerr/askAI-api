"""The derived floor, read back with the evidence it was derived from.

Purity: reads the packaged rule files (cached by the loader); pure thereafter.

AD-30's last clause is the one this module exists for: *"the derivation is recorded with
the value ... re-derived whenever the embedding model, the chunking, or the corpus
changes -- any of which moves the scoring space."* A floor is therefore not a number here.
It is a number **plus** the labelled set it came from and the vector source it was
measured against, and the only way to read the number is to present a vector source and
have it agree.

That makes the dangerous case unrepresentable rather than discouraged. A floor derived
against hashed character trigrams describes the score distribution of hashed character
trigrams and nothing else; applied to a 768-dimension model's cosines it would be a
number from one scoring space used as a threshold in another, which is the same class of
confident nonsense that ``IndexLoadError`` refuses at load time. The index already
records its source identity for exactly that reason, and this compares against the same
string, so the two refusals cannot disagree about what a source is.

Reading the floor does not gate on whether the derivation was *sufficient*: that is a
separate published fact (:func:`floor_is_sufficient`), because a floor measured to be
insufficient is evidence for AD-30's structural discriminator and suppressing it here
would leave a caller unable to find out.
"""

from __future__ import annotations

from typing import Final

from askai.ports.vectors import VectorSourcePort
from askai.rules import rules

__all__ = [
    "CRITERION_RULE",
    "CUT_RULE",
    "FLOOR_RULE",
    "StaleDerivationError",
    "derivation_criterion",
    "derived_from_set",
    "floor_is_sufficient",
    "relative_cut",
    "resolution_floor",
]

FLOOR_RULE: Final = "R-NAMES-RESOLUTION-FLOOR"
CUT_RULE: Final = "R-NAMES-RELATIVE-CUT-AGAINST-BEST-HIT"
CRITERION_RULE: Final = "R-NAMES-FLOOR-DERIVATION-CRITERION"

_PER_CENT: Final = 100


class StaleDerivationError(RuntimeError):
    """A derived value is being read against something it was not derived against.

    Raised rather than returned as a default, for the reason ``IndexLoadError`` is raised
    rather than degraded: a threshold from another scoring space does not fail, it
    silently admits or refuses the wrong candidates, and every symptom of it looks like a
    retrieval quality problem somewhere else.
    """


def _number(rule_id: str, key: str) -> int:
    value = rules().value(rule_id, key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StaleDerivationError(f"{rule_id} value `{key}` is {value!r}; it is a whole number")
    return value


def _text(rule_id: str, key: str) -> str:
    value = rules().value(rule_id, key)
    if not isinstance(value, str):
        raise StaleDerivationError(f"{rule_id} value `{key}` is {value!r}; it is text")
    return value


def _flag(rule_id: str, key: str) -> bool:
    value = rules().value(rule_id, key)
    if not isinstance(value, bool):
        raise StaleDerivationError(f"{rule_id} value `{key}` is {value!r}; it is true or false")
    return value


def _verify(rule_id: str, source: VectorSourcePort) -> None:
    recorded = _text(rule_id, "vector_source_identity")
    if recorded != source.identity:
        raise StaleDerivationError(
            f"{rule_id} was derived against {recorded!r} and is being read against "
            f"{source.identity!r}. A threshold belongs to the scoring space it was "
            "measured in; changing the vector source means re-deriving it over the "
            "labelled set, exactly as changing it means rebuilding the index."
        )


def resolution_floor(source: VectorSourcePort) -> float:
    """The lowest combined score a candidate may carry and still be offered, for *source*.

    Refuses a source other than the one the value was derived against, by name.
    """
    _verify(FLOOR_RULE, source)
    return _number(FLOOR_RULE, "floor_percent") / _PER_CENT


def relative_cut(source: VectorSourcePort) -> float:
    """The share of the best hit's score a later candidate must reach to be offered too.

    The inherited relative cut of Story 2.13's last criterion, derived from the same set
    and refused against the same mismatch, so that a good first suggestion is not followed
    by two bad ones.
    """
    _verify(CUT_RULE, source)
    return _number(CUT_RULE, "relative_cut_percent") / _PER_CENT


def derived_from_set(rule_id: str = FLOOR_RULE) -> str:
    """The labelled-set identity a derived value records -- ``<name>-v<version>``.

    The staleness check AD-30 asks CI for is this string against the set on disk: a floor
    whose recorded set is not the one the build holds was derived from distributions that
    no longer exist.
    """
    return _text(rule_id, "labelled_set")


def floor_is_sufficient() -> bool:
    """Whether the measured distributions were separated enough for a floor to carry them.

    ``False`` is AD-30's finding, not an error: *a flat score cannot carry a distinction
    the index never encoded*, and the structural discriminator of Story 2.4 is then
    required rather than a different number.
    """
    return _flag(FLOOR_RULE, "sufficient")


def derivation_criterion() -> tuple[float, float, float]:
    """The declared budget a derivation is judged against: high share, then the two rates.

    Returned together because they are one criterion; reading them apart is how two call
    sites come to disagree about what "materially overlapping" meant.
    """
    return (
        _number(CRITERION_RULE, "irrelevant_percentile") / _PER_CENT,
        _number(CRITERION_RULE, "maximum_false_negative_percent") / _PER_CENT,
        _number(CRITERION_RULE, "maximum_false_positive_percent") / _PER_CENT,
    )
