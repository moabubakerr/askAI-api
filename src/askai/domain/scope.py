"""``CountryScope`` -- national scope is a query shape, never a country value.

Purity: pure, imports nothing in-project.

The benchmark configuration names the home country in all 21 declared sets; the data
names it in none of its 8,127 rows, where national scope is the *absence* of a country
value. So any implementation that reads the declared list and looks each country up by
name retrieves every benchmark and silently drops the home country from its own
comparison (AD-5, FR-10, FR-11b).

The fix is structural rather than careful: ``National`` has no field to put a country
in, so a national query cannot carry one. ``tests/test_domain_invariants.py`` asserts
the home country's name appears as a literal nowhere in ``domain/`` -- including in
this docstring, which is why it is described rather than named.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["CountryScope", "DeclaredBenchmarks", "Named", "National"]


@dataclass(frozen=True, slots=True)
class National:
    """The home country's own series: the rows carrying no country value at all.

    Deliberately empty. There is nowhere to put a country id, so the blank-country
    marker cannot be back-filled into a filter value by any call site.
    """


@dataclass(frozen=True, slots=True)
class Named:
    """A country set the reader named, which filters the benchmarks and never widens them."""

    countries: frozenset[str]

    def __post_init__(self) -> None:
        # Coerced, not merely annotated: a plain `set` passed at runtime would make the
        # enclosing QuerySpec unhashable, and a spec that cannot be hashed cannot be a
        # cache key or a log field (spine conventions, Logging).
        if not isinstance(self.countries, frozenset):
            coerced: Iterable[str] = self.countries
            object.__setattr__(self, "countries", frozenset(coerced))
        if not self.countries:
            # An empty named set filters every benchmark away while being
            # indistinguishable from a scope nobody set. National() and
            # DeclaredBenchmarks() are the two ways to mean "not a named list".
            raise ValueError(
                "Named requires at least one country; use National() or "
                "DeclaredBenchmarks() to express a scope with no named list"
            )


@dataclass(frozen=True, slots=True)
class DeclaredBenchmarks:
    """Whatever benchmark set the detail itself declares -- 21 of 289 details declare one."""


#: The closed set. A cross-country answer is the union of a national selection and a
#: benchmark selection, assembled in one place; it is never a single widened filter.
type CountryScope = National | Named | DeclaredBenchmarks
