"""The one place a cross-country answer decides who is in it (AD-5, FR-9, FR-11b).

Purity: pure. Reads its constants from ``rules/``; holds no country list and no bound
of its own.

A cross-country answer is **the union of a national selection and a benchmark
selection**. That sentence is the whole of AD-5, and the reason it is a sentence about
*assembly* rather than about fetching is F-001: the benchmark configuration names the
home country in all 21 declared sets while the published data names it in none of its
8,127 rows, so an implementation that reads the declared list and looks each country up
by name retrieves every benchmark and silently drops the home country from its own
comparison. The answer looks complete. It is missing the country the reader asked about.

So the union is formed here, once, and the two halves are different fields of different
types:

* ``Selection.national`` is a **flag**, because the national selection has no country to
  carry -- it is the rows with no country value at all.
* ``Selection.codes`` is a set of ISO codes, produced by ``filter_values()``, which
  ``rules/countries.py`` wrote so that ``HomeCountry`` *structurally cannot* appear in
  it. There is no attribute on the type to lift a code out of.

**Named countries filter; they never expand.** A reader who names a country the detail
does not declare as a benchmark is told so (``not_declared``); the set does not grow to
accommodate the name, and nothing is fetched for it. That is
``R-COMPARE-NAMED-COUNTRIES-FILTER-THE-DECLARED-SET``, read as a switch rather than
written as behaviour, because the opposite is what the predecessor did.

**"Not a declared benchmark" and "no rows" are different answers**, and the split runs
through this module and out the other side. Everything this module can see is
*configuration*: whether the detail declares a set at all, and whether a named country
is in it. Whether a declared country published anything is a fact about rows, and is
decided where the rows are -- ``countries.py``, on the readings. 268 of 289 details
declare no set and one of the 21 that do declares nine countries and publishes zero
country rows, so both refusals are ordinary outcomes rather than edge cases, and a
reader has to be able to tell a configuration gap from a data gap.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from askai.domain.scope import CountryScope, DeclaredBenchmarks, Named, National
from askai.rules import RuleSet, RuleValue
from askai.rules.countries import (
    CountryAliases,
    CountryIdentity,
    HomeCountry,
    filter_values,
)

__all__ = [
    "CompareClause",
    "CompareRule",
    "Declaration",
    "NotComparable",
    "Selection",
    "SelectionOutcome",
    "SelectionRefusal",
    "SelectionRuleError",
    "fan_out_bound",
    "named_countries_may_expand",
    "select",
]


class CompareRule(StrEnum):
    """The rule ids this package reads. Ids, not values -- the values stay in the file."""

    FILTER_NEVER_EXPAND = "R-COMPARE-NAMED-COUNTRIES-FILTER-THE-DECLARED-SET"
    FAN_OUT = "R-COMPARE-FAN-OUT-BOUND"
    SPREAD_IN_POINTS = "R-COMPARE-SPREAD-OVER-PERCENT-IS-POINTS"
    POLARITY_DECIDES_BEST = "R-COMPARE-POLARITY-DECIDES-BEST"
    RANK_IS_NEVER_COMPUTED = "R-COMPARE-RANK-IS-NEVER-COMPUTED"
    ORDINAL_NAMED_POSITIONS = "R-COMPARE-ORDINAL-NAMED-POSITIONS"


class CompareClause(StrEnum):
    """The clause names those rules carry."""

    MAY_EXPAND = "named_countries_may_expand"
    MAX_CONCURRENT_FETCHES = "max_concurrent_fetches"
    PERCENT_UNITS = "percent_units"
    POINTS_UNIT = "points_unit"
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    RANKS_ARE_COMPUTED = "ranks_are_computed"
    NAMED_POSITIONS = "named_positions"


class SelectionRuleError(LookupError):
    """A comparison rule is missing or is not the shape the selection needs.

    Raised rather than defaulted. A fan-out bound that silently fell back to one would
    turn NFR-2's concurrent fetch into a serial one on the day the file was edited, and
    a filter switch that silently fell back would reopen F-001.
    """


class SelectionRefusal(StrEnum):
    """Why there is no cross-country selection to make. Codes, never sentences.

    The two members are the two *configuration* gaps, and they are separate because a
    reader has to be able to tell them apart: one says this indicator was never set up
    for comparison, the other says it was, but not with the country you asked about.
    Both are honest refusals and the acceptance criteria weight them as heavily as a
    comparison -- cross-country comparison reaches 21 of 289 details.
    """

    NO_DECLARED_SET = "indicator-declares-no-benchmark-countries"
    """268 of 289 details. Nothing was configured, so nothing was withheld."""

    NO_NAMED_COUNTRY_IS_DECLARED = "no-named-country-is-a-declared-benchmark"
    """Every country the reader named sits outside the declared set. Naming them does
    not add them, so there is nobody left to compare."""


@dataclass(frozen=True, slots=True)
class Declaration:
    """The benchmark set a detail declares, as resolved identities.

    ``declared`` is what the published configuration names, already through the alias
    map -- so the two published spellings of one country have collapsed to one identity
    before anything is fetched, and the home country is a ``HomeCountry`` rather than a
    name that would match no row.

    A detail declaring nothing is this type with an empty tuple, not ``None``. "This
    indicator declares no benchmark countries" is a fact the answer states, and a value
    that can be absent invites a call site to treat it as unknown.
    """

    detail_id: str
    declared: tuple[CountryIdentity, ...] = ()

    def __post_init__(self) -> None:
        if not self.detail_id.strip():
            raise ValueError("a declaration belongs to a detail; it needs the detail's id")

    @property
    def declares_a_set(self) -> bool:
        return bool(self.declared)

    @property
    def home_is_declared(self) -> bool:
        """Is the home country one of the declared benchmarks? In all 21 sets, yes.

        Asked by identity and not by name. There is no name here to compare against,
        which is the point -- a comparison by name is the F-001 defect written out.
        """
        return any(isinstance(one, HomeCountry) for one in self.declared)

    @property
    def codes(self) -> frozenset[str]:
        """The declared benchmark countries a filter may carry.

        Through ``filter_values()``, so the home country cannot be in it: it carries no
        code, so there is nothing to put in the set (AD-5).
        """
        return filter_values(self.declared)


@dataclass(frozen=True, slots=True)
class Selection:
    """Who a cross-country answer covers: a national half and a benchmark half.

    Frozen, and the two halves stay separate all the way through. Nothing here offers a
    combined "countries to fetch" list, because a combined list is the shape that has to
    put the home country in it or drop it, and both are wrong.
    """

    detail_id: str

    national: bool
    """Whether the rows with no country value are part of this answer. A flag, because
    the national selection has no country to name (AD-5, ``domain.scope.National``)."""

    codes: frozenset[str]
    """The benchmark countries to fetch, by ISO code. Never contains the home country:
    it comes from ``filter_values()``, which has nothing to emit it from."""

    not_declared: tuple[str, ...] = ()
    """Countries the reader named that the detail does not declare. Reported, never
    fetched -- naming a country filters the declared set and does not widen it."""

    unresolved: tuple[str, ...] = ()
    """Names no alias group claims. Kept separate from ``not_declared`` because "we do
    not know that country" and "that country is not a benchmark here" are different
    things to tell a reader, and FR-110 says neither is dropped silently."""

    fan_out: int = 1
    """The most fetches this selection may have in flight at once (NFR-2). Stated by the
    selection and respected by whoever performs the fetch, so the bound travels with the
    set it bounds rather than being re-derived beside it."""

    @property
    def is_cross_country(self) -> bool:
        """Does this answer line up more than one series?

        True for a national half plus any benchmark, and for two benchmarks with no
        national half. False for a single series, which is another story's fetch.
        """
        return len(self.codes) + int(self.national) > 1

    @property
    def covered(self) -> int:
        """How many series this selection covers, the national one included."""
        return len(self.codes) + int(self.national)


@dataclass(frozen=True, slots=True)
class NotComparable:
    """There is no selection to make, and this is which of the two reasons it is.

    ``named`` carries the countries the reader asked about, so the answer can say what
    it could not do with them rather than refusing in the abstract.
    """

    detail_id: str
    refusal: SelectionRefusal
    named: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()


#: What ``select`` returns. Closed, so a caller that handles the selection and forgets
#: the refusal does not type-check -- which is the foreclosure rather than a convention.
type SelectionOutcome = Selection | NotComparable


def named_countries_may_expand(rule_set: RuleSet) -> bool:
    """May naming a country add it to the declared benchmark set? (FR-9: no.)

    Read rather than assumed, and read on every selection. The value it returns decides
    nothing in this module's happy path -- the filter is written as a filter -- but a
    build where the file says ``true`` and the code filters anyway is a build whose rule
    files are decorative, so the disagreement is raised instead of ignored.
    """
    return _switch(rule_set, CompareRule.FILTER_NEVER_EXPAND, CompareClause.MAY_EXPAND)


def fan_out_bound(rule_set: RuleSet) -> int:
    """How many country fetches may be in flight at once (NFR-2)."""
    bound = _whole_number(rule_set, CompareRule.FAN_OUT, CompareClause.MAX_CONCURRENT_FETCHES)
    if bound < 1:
        raise SelectionRuleError(
            f"{CompareRule.FAN_OUT.value} bounds the fan-out at {bound}, which fetches "
            "nothing; a bound of one is a serial fetch and is the smallest it can be"
        )
    return bound


def select(
    scope: CountryScope,
    declaration: Declaration,
    aliases: CountryAliases,
    rule_set: RuleSet,
) -> SelectionOutcome:
    """Who this answer covers, given what the reader asked for and what the detail declares.

    Exhaustive over the closed ``CountryScope``. A member added later fails here rather
    than falling through to an empty selection, which would be "nobody to compare"
    wearing an omission's clothes.
    """
    if named_countries_may_expand(rule_set):
        raise SelectionRuleError(
            f"{CompareRule.FILTER_NEVER_EXPAND.value} says a named country may expand "
            "the declared benchmark set, and this selection filters; F-001 is a "
            "two-country question that returned six, so the disagreement is raised "
            "rather than resolved in favour of either side"
        )
    bound = fan_out_bound(rule_set)
    match scope:
        case National():
            # Not a refusal and not a comparison: the reader asked about the national
            # series, and the national series is exactly what this covers.
            return Selection(
                detail_id=declaration.detail_id,
                national=True,
                codes=frozenset(),
                fan_out=bound,
            )
        case DeclaredBenchmarks():
            return _whole_declared_set(declaration, bound)
        case Named(countries=surfaces):
            return _filtered(surfaces, declaration, aliases, bound)
        case _:
            raise TypeError(
                f"{type(scope).__name__} is not a CountryScope member, or is one this "
                "selection has not been told about; say how it meets a declared "
                "benchmark set before an answer is assembled from it"
            )


def _whole_declared_set(declaration: Declaration, bound: int) -> SelectionOutcome:
    """The detail's own declared set -- the union, with nothing filtered out of it."""
    if not declaration.declares_a_set:
        return NotComparable(
            detail_id=declaration.detail_id,
            refusal=SelectionRefusal.NO_DECLARED_SET,
        )
    return Selection(
        detail_id=declaration.detail_id,
        # The home country is in all 21 declared sets, and this is where that becomes a
        # national selection rather than a country filter value.
        national=declaration.home_is_declared,
        codes=declaration.codes,
        fan_out=bound,
    )


def _filtered(
    surfaces: Iterable[str], declaration: Declaration, aliases: CountryAliases, bound: int
) -> SelectionOutcome:
    """The named countries, intersected with the declared set and never added to it.

    Resolution happens before the intersection, so a reader naming either published
    spelling of a country meets the same declared identity -- keying by code collapses
    the duplicate by data rather than by opinion.

    **The national half is included when the reader named the home country, and not
    otherwise.** It is tempting to always include it, since it is declared in all 21 sets
    and it is whose benchmark set this is -- but adding a series nobody asked for is
    expansion, which is exactly what this function exists to refuse, and an answer that
    grows is as hard to defend as one that shrinks. FR-11b is about what happens when the
    reader *does* name it: it arrives as ``national=True``, a query shape with no filter,
    rather than as a code that would match none of the 8,127 published rows.
    """
    # Sorted so the same question produces the same selection on every run (AD-17); a
    # `Named` scope carries a frozenset, whose iteration order is not stable across
    # processes, and an answer listing countries in a different order each time is an
    # answer a QC tester cannot diff.
    named = tuple(sorted(surfaces))
    resolution = aliases.resolve_all(named)
    declared = frozenset(declaration.declared)

    if not declaration.declares_a_set:
        # The configuration gap wins over the country gap, and deliberately: telling a
        # reader that Japan is not a declared benchmark for an indicator that declares
        # none at all answers a question they did not ask.
        return NotComparable(
            detail_id=declaration.detail_id,
            refusal=SelectionRefusal.NO_DECLARED_SET,
            named=named,
            unresolved=resolution.unmapped,
        )

    kept = tuple(one for one in resolution.identities if one in declared)
    not_declared = _named_but_not_declared(named, aliases, declared)
    if not kept:
        return NotComparable(
            detail_id=declaration.detail_id,
            refusal=SelectionRefusal.NO_NAMED_COUNTRY_IS_DECLARED,
            named=named,
            unresolved=resolution.unmapped,
        )
    return Selection(
        detail_id=declaration.detail_id,
        national=any(isinstance(one, HomeCountry) for one in kept),
        codes=filter_values(kept),
        not_declared=not_declared,
        unresolved=resolution.unmapped,
        fan_out=bound,
    )


def _named_but_not_declared(
    named: tuple[str, ...], aliases: CountryAliases, declared: frozenset[CountryIdentity]
) -> tuple[str, ...]:
    """The surface forms that resolved to a country the detail does not declare.

    The reader's own spelling comes back, not the code: an answer that says a country is
    not a declared benchmark is read by the person who named it, and an ISO code is not
    what they said.
    """
    outside: list[str] = []
    for surface in named:
        identity = aliases.resolve(surface)
        if identity is None or identity in declared:
            continue
        if surface not in outside:
            outside.append(surface)
    return tuple(outside)


def _switch(rule_set: RuleSet, rule: CompareRule, clause: CompareClause) -> bool:
    value = rule_set.value(rule.value, clause.value)
    if not isinstance(value, bool):
        raise SelectionRuleError(_wrong_shape(rule, clause, "a yes or a no", value))
    return value


def _whole_number(rule_set: RuleSet, rule: CompareRule, clause: CompareClause) -> int:
    value = rule_set.value(rule.value, clause.value)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SelectionRuleError(_wrong_shape(rule, clause, "a whole number", value))
    return value


def _wrong_shape(
    rule: CompareRule, clause: CompareClause, wanted: str, found: RuleValue
) -> str:
    return (
        f"{rule.value} value `{clause.value}` must be {wanted}, not "
        f"{type(found).__name__}; the comparison reads its constants from the rule "
        "files and has none of its own to fall back to"
    )
