"""The single ``Formatter`` -- the one route from a published value to a string.

Purity: pure. Reads the rounding rules from ``rules/`` and the digits and separators
from ``messages/``; holds no constant of its own.

AD-18: *"A single Formatter converts a value to a string, taking the detail's published
format and an explicit FormatMode(Headline | Evidence). Headline applies the display
rounding rule; Evidence preserves published precision. No composer may build a numeric
string by any other route."* That last sentence is the one with teeth, and
``tests/test_assemble.py`` asserts it as a scan rather than trusting it: the defect it
prevents is F-004, where one row reached a card twice at two precisions because two
composers each formatted it where they found it.

Three things are deliberately *not* here.

**No constant.** The display decimals come from
``R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT`` and its ``fallback_decimals``, the rank
decimals from ``R-DISPLAY-RANK-IS-AN-INTEGER-ORDINAL``, the silent placeholder units
from ``R-DISPLAY-PLACEHOLDER-UNIT-IS-SILENT``, and the unit spellings that mark a rank
from ``R-DISPLAY-RANK-UNIT-SPELLINGS``. Every one is read through
``RuleSet.value(...)``; ``tests/test_rules.py`` scans this package for the literal that
would make those files decorative.

**No wording, and no joining.** The formatter returns the numeral and the unit as two
fields and never concatenates them. Whether a unit follows its figure with a space, with
none, or before it at all is an editorial decision per language, and the catalogue
already makes it -- ``answer.value`` places ``{value}`` and ``{unit}`` itself. A
separator chosen here would be reader-facing text living outside ``messages/``.

**No conversion between ``Percent`` and ``PercentagePoints``.** Both are accepted and
each is rendered from its own ``Decimal``; there is no arithmetic, no ``float()`` and no
construction of either type anywhere in this package, which the tests assert
structurally. Formatting is where the F-005 conflation would be easiest to introduce and
hardest to see, because both would render as plausible numerals.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from askai.domain.normalise import normalise
from askai.domain.numbers import Percent, PercentagePoints
from askai.messages import Catalogue, Lang, format_value
from askai.rules import RuleSet, RuleValue

__all__ = [
    "DisplayClause",
    "DisplayRule",
    "FormatMode",
    "FormattedValue",
    "Formatter",
    "PublishedFormat",
    "published_decimals",
]


class FormatMode(StrEnum):
    """Where in the answer the figure sits, which is what decides its precision.

    A property of the position, decided once, never chosen per composer (AD-18, FR-48).
    There is no third member and no default anywhere: a call site that has not been told
    where its figure sits cannot format it.
    """

    HEADLINE = "headline"
    """The figure the reader reads first. Takes the display rounding rule."""

    EVIDENCE = "evidence"
    """The same figure, shown as published. Preserves the published precision exactly,
    so a reader who checks the headline against the evidence sees where it came from."""


class DisplayRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the files."""

    DECIMALS_FROM_PUBLISHED_FORMAT = "R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT"
    RANK_IS_AN_INTEGER_ORDINAL = "R-DISPLAY-RANK-IS-AN-INTEGER-ORDINAL"
    PLACEHOLDER_UNIT_IS_SILENT = "R-DISPLAY-PLACEHOLDER-UNIT-IS-SILENT"
    RANK_UNIT_SPELLINGS = "R-DISPLAY-RANK-UNIT-SPELLINGS"


class DisplayClause(StrEnum):
    """The clause names read off those rules."""

    FALLBACK_DECIMALS = "fallback_decimals"
    DECIMALS = "decimals"
    SILENT_UNITS = "silent_units"
    RANK_UNITS = "rank_units"


#: What the formatter accepts. ``Decimal`` and the two percentage types, and nothing
#: else -- a ``float`` has already lost the published value (AD-4), and an ``int`` that
#: has not been read as a ``Decimal`` came from somewhere other than the published row.
type Figure = Decimal | Percent | PercentagePoints


@dataclass(frozen=True, slots=True)
class PublishedFormat:
    """The detail's published unit and Format field, as the catalogue publishes them.

    Both are carried as published, including the placeholder unit and the empty Format:
    cleaning them at the boundary would put the display decision in the boundary, and
    the two rules that handle those cases would have nothing left to fire on.
    """

    unit: str
    spec: str


@dataclass(frozen=True, slots=True)
class FormattedValue:
    """A figure, written -- as two fields, because a unit is not part of a numeral."""

    value: str
    """The numeral, in the language's own digits and separators."""

    unit: str
    """The unit to show, or empty when the published unit is a silent placeholder."""

    decimals: int
    """How many decimals the numeral actually carries -- recorded so an answer record can
    say what the reader saw, rather than what the rule would have produced."""


def published_decimals(spec: str) -> int | None:
    """How many decimals the published Format field asks for, or ``None`` if it says
    nothing.

    The published Format field is a display pattern -- ``0.0``, ``00``, ``bn0.0`` -- in
    which ``0`` and ``#`` are digit positions and everything else is decoration. So the
    decimals are the digit positions after the decimal point, a pattern with positions
    but no point asks for none, and a field carrying no positions at all (the empty one,
    which is what produced ``11.00 Rank``) has said nothing and falls through to the
    rule's fallback.
    """
    # Local to this function on purpose: it is the publisher's pattern grammar, not a
    # reader-affecting decision, and a module-level name would be the literal the scan
    # in tests/test_rules.py exists to catch.
    positions = "0#"
    pattern = spec.strip()
    if not any(character in positions for character in pattern):
        return None
    _, point, fraction = pattern.rpartition(".")
    if not point:
        return 0
    return sum(1 for character in fraction if character in positions)


@dataclass(frozen=True, slots=True)
class Formatter:
    """The one formatter. Constructed with the catalogue and the rules, used everywhere.

    It is a value rather than a module of functions so that the catalogue and the rule
    set are *handed* to it: a module-level catalogue would be the ambient state AD-2
    forbids, and a module-level rule set would read a file on every answer.
    """

    catalogue: Catalogue
    rule_set: RuleSet

    def format(
        self, value: Figure, published: PublishedFormat, mode: FormatMode, lang: Lang
    ) -> FormattedValue:
        """Write *value* under *published*, at the precision *mode* calls for, in *lang*.

        Neither ``mode`` nor ``lang`` has a default, and neither ever will. A default
        mode is how a headline acquires evidence precision on the one card nobody
        checked; a default language is how an English sentence reaches an Arabic answer.
        """
        figure = _published_value(value)
        shown = (
            figure
            if mode is FormatMode.EVIDENCE
            else _rounded(figure, self.display_decimals(published))
        )
        return FormattedValue(
            value=format_value(self.catalogue, lang, shown),
            unit=self.display_unit(published),
            decimals=_decimals_of(shown),
        )

    def display_decimals(self, published: PublishedFormat) -> int:
        """The decimals a headline shows *published* to, by the rules and nothing else."""
        if self.is_rank(published):
            return _whole_number(
                self.rule_set, DisplayRule.RANK_IS_AN_INTEGER_ORDINAL, DisplayClause.DECIMALS
            )
        declared = published_decimals(published.spec)
        if declared is None:
            return _whole_number(
                self.rule_set,
                DisplayRule.DECIMALS_FROM_PUBLISHED_FORMAT,
                DisplayClause.FALLBACK_DECIMALS,
            )
        return declared

    def display_unit(self, published: PublishedFormat) -> str:
        """The unit a reader is shown -- empty for a placeholder the catalogue publishes.

        ``R-DISPLAY-PLACEHOLDER-UNIT-IS-SILENT``: *"NA"* is a placeholder, not a unit,
        and a figure carrying it is shown with no unit rather than with the word.
        """
        silent = self._spellings(
            DisplayRule.PLACEHOLDER_UNIT_IS_SILENT, DisplayClause.SILENT_UNITS
        )
        if _matches(published.unit, silent):
            return ""
        return published.unit.strip()

    def is_rank(self, published: PublishedFormat) -> bool:
        """Whether *published* names a rank, by the spellings the rule file carries."""
        return _matches(
            published.unit,
            self._spellings(DisplayRule.RANK_UNIT_SPELLINGS, DisplayClause.RANK_UNITS),
        )

    def _spellings(self, rule: DisplayRule, clause: DisplayClause) -> tuple[str, ...]:
        return _spelling_list(self.rule_set, rule, clause)


def _published_value(value: Figure) -> Decimal:
    """The ``Decimal`` inside a figure, with no conversion between the two unit types.

    ``Percent`` and ``PercentagePoints`` each hand over their own value and neither is
    ever built from the other -- there is no construction of either type in this
    package, which ``tests/test_assemble.py`` asserts by scanning for one.
    """
    match value:
        case Decimal():
            figure = value
        case Percent() | PercentagePoints():
            figure = value.value
        case _:
            # Unreachable under `mypy --strict`, and reached the moment something
            # untyped hands over a float -- which is the call this guard exists for.
            raise TypeError(
                f"the formatter takes a Decimal, a Percent or percentage points, not "
                f"{type(value).__name__}; a float has already lost the published value"
            )
    if not figure.is_finite():
        raise ValueError(f"the formatter takes a finite published value, not {figure}")
    return figure


def _rounded(figure: Decimal, decimals: int) -> Decimal:
    """*figure* at *decimals* places, half away from zero.

    ``ROUND_HALF_UP`` rather than the ``decimal`` default of half-to-even: the published
    figures are presentation values a reader checks against a published table, and
    banker's rounding would disagree with that table on exactly the values a reader is
    most likely to spot.
    """
    return figure.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _decimals_of(figure: Decimal) -> int:
    exponent = figure.as_tuple().exponent
    if isinstance(exponent, int) and exponent < 0:
        return -exponent
    return 0


def _matches(unit: str, spellings: tuple[str, ...]) -> bool:
    """Whether *unit* is one of *spellings*, under the engine's single text fold.

    ``domain.normalise`` and not a comparison written here: a second fold is the defect
    ``tests/test_normalise.py`` bans outright, and "NA " failing to match "NA" would be
    a unit word reaching a reader because of a trailing space in an export.
    """
    folded = normalise(unit)
    return any(folded == normalise(spelling) for spelling in spellings)


def _whole_number(rule_set: RuleSet, rule: DisplayRule, clause: DisplayClause) -> int:
    value = rule_set.value(rule.value, clause.value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(_wrong_shape(rule, clause, "a whole number of decimals", value))
    return value


def _spelling_list(rule_set: RuleSet, rule: DisplayRule, clause: DisplayClause) -> tuple[str, ...]:
    value = rule_set.value(rule.value, clause.value)
    if not isinstance(value, tuple):
        raise TypeError(_wrong_shape(rule, clause, "a list of published spellings", value))
    return value


def _wrong_shape(rule: DisplayRule, clause: DisplayClause, wanted: str, found: RuleValue) -> str:
    return (
        f"{rule.value} value `{clause.value}` must be {wanted}, not "
        f"{type(found).__name__}; the formatter reads its constants from the rule files "
        f"and has none of its own to fall back to"
    )
