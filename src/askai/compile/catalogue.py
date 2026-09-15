"""A catalogue snapshot the binder can hold: names in, identifiers out.

Purity: pure.

``CataloguePort`` says what binding may ask; this is the in-memory answer to it, built
from whatever the caller has -- the read model, in the story that wires ingest to the
answer path, and a handful of entries in a test. It lives in ``compile/`` rather than in
an adapter because it holds no connection and reads no file: it is the shape of the
question the binder asks, and an adapter's job is to fill it.

The names are folded once at construction by the engine's single ``normalise``, and
looked up by equality. That is the whole of Epic 1's resolution -- exact normalised-name
lookup -- and there is deliberately nothing here to extend into a score.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from askai.domain.normalise import normalise
from askai.domain.period import Grain

__all__ = ["CatalogueCountry", "CatalogueDetail", "SnapshotCatalogue", "snapshot"]


@dataclass(frozen=True, slots=True)
class CatalogueDetail:
    """One detail as binding sees it: its published names and the grains it publishes at.

    ``declared_grain`` is the grain the catalogue *declares* as the detail's default, and
    it is ``None`` when the catalogue declares none. It is never derived from the
    datapoints: FR-5's entire content is that the newest row does not get to decide.
    """

    detail_id: str
    names: tuple[str, ...]
    declared_grain: Grain | None = None
    grains: frozenset[Grain] = frozenset()


@dataclass(frozen=True, slots=True)
class CatalogueCountry:
    """One country as binding sees it. The home country is in no published row and so is
    in no snapshot; naming it finds nothing and the scope falls to national (AD-5)."""

    country_id: str
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SnapshotCatalogue:
    """Every published name, folded once, with the detail or country it names.

    Two details published under one name are both returned rather than one being
    preferred: 257 of 320 published names are ambiguous, and choosing between them is
    resolution's job in Epic 2, not a tie-break hidden in a lookup table.
    """

    details: tuple[CatalogueDetail, ...] = ()
    countries: tuple[CatalogueCountry, ...] = ()
    _details_by_name: Mapping[str, tuple[str, ...]] = field(init=False, repr=False, compare=False)
    _countries_by_name: Mapping[str, str] = field(init=False, repr=False, compare=False)
    _by_id: Mapping[str, CatalogueDetail] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        by_name: dict[str, list[str]] = {}
        for detail in self.details:
            for name in detail.names:
                by_name.setdefault(normalise(name), []).append(detail.detail_id)
        object.__setattr__(
            self,
            "_details_by_name",
            {name: tuple(sorted(set(ids))) for name, ids in by_name.items()},
        )
        object.__setattr__(
            self,
            "_countries_by_name",
            {
                normalise(name): country.country_id
                for country in self.countries
                for name in country.names
            },
        )
        object.__setattr__(
            self, "_by_id", {detail.detail_id: detail for detail in self.details}
        )

    def details_named(self, normalised_name: str) -> tuple[str, ...]:
        return self._details_by_name.get(normalised_name, ())

    def default_grain(self, detail_id: str) -> Grain | None:
        entry = self._by_id.get(detail_id)
        return None if entry is None else entry.declared_grain

    def published_grains(self, detail_id: str) -> frozenset[Grain]:
        entry = self._by_id.get(detail_id)
        return frozenset() if entry is None else entry.grains

    def country_named(self, normalised_name: str) -> str | None:
        return self._countries_by_name.get(normalised_name)


def snapshot(
    details: Sequence[CatalogueDetail] = (), countries: Sequence[CatalogueCountry] = ()
) -> SnapshotCatalogue:
    """A snapshot from any sequence -- the shape an adapter builds one in."""
    return SnapshotCatalogue(details=tuple(details), countries=tuple(countries))
