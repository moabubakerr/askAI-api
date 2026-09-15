"""Country identity: a surface form in, one country -- or the national scope -- out.

Purity: reads the packaged rule files once; pure thereafter.

FR-11a asks for an alias map *held as data a steward can review*, and AD-5 says what the
map must never produce. Both constraints land here, and neither is a convention:

**No country list lives in this module.** Every code, every English name and every Arabic
name is in ``data/country-aliases.yaml``; this file holds the parser for that table, the
fold it looks names up by, and nothing a reader of an answer would recognise. Adding a
country is a data edit.

**The home country resolves to a scope, not to a value.** The configuration names it in
all 21 declared benchmark sets while the published data names it in none of its 8,127
rows -- there, the national series is the *absence* of a country value. So its group in
the table is marked by code, ``resolve()`` returns ``HomeCountry()`` for it, and
``HomeCountry`` has no ``code`` attribute to put in a filter. ``filter_values()`` cannot
emit it because there is nothing on the type to emit; that is the structural half of AD-5,
matching ``domain.scope.National``, which likewise has nowhere to put a country.

**Lookup goes through the one fold.** AD-26 names alias lookup as a call site of the
single ``normalise()`` in ``domain/``, so a group written with a hamza the reader omits,
a harakat the export carries, or a case the question does not, still meets the question.
There is no second fold here and no per-call option on the one there is.

The duplicate that prompted the story falls out of the keying rather than being special-
cased: the export carries ``Korea`` and ``South Korea`` as two country ids with one ISO
code, so a group is keyed by the code and both names sit in it. A reader naming either
reaches one identity, and a declared benchmark set carrying both yields that identity once
-- collapsed at resolution, before any row is fetched, because a set de-duplicated after
the fetch has already shown the country twice.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from askai.domain.normalise import normalise
from askai.rules.loader import RuleLoadError, RuleSet, rules

__all__ = [
    "ALIAS_GROUPS_RULE",
    "HOME_COUNTRY_RULE",
    "Country",
    "CountryAliasError",
    "CountryAliases",
    "CountryIdentity",
    "HomeCountry",
    "ReferenceCountry",
    "Resolution",
    "country_aliases",
    "filter_values",
    "load_country_aliases",
]

#: The two rules this module reads. Named here so a rename in the data file fails at
#: startup with a message naming the rule, rather than resolving every country to nothing.
ALIAS_GROUPS_RULE: Final = "R-COUNTRY-ALIAS-GROUPS"
HOME_COUNTRY_RULE: Final = "R-COUNTRY-HOME-IS-ABSENCE"

#: A group is `CODE | form | form | ...`. The separator is a file format, not a rule: it
#: decides nothing a reader of an answer ever sees, and changing it changes no behaviour.
_SEPARATOR: Final = "|"

#: ISO 3166-1 alpha-2. A shape constraint on the file's own keys, not a rule about
#: countries -- there is no version of this map in which a code is three letters long.
_CODE_LENGTH: Final = 2


class CountryAliasError(RuleLoadError):
    """The alias table is missing, malformed, or claims one surface form twice.

    A subclass of ``RuleLoadError`` because it is the same failure at the same moment:
    the engine does not start with a country map it cannot trust, and an operator who
    catches rule-load failures catches this one too.
    """


@dataclass(frozen=True, slots=True)
class HomeCountry:
    """The country the data expresses as the absence of a country.

    Deliberately empty, exactly as ``domain.scope.National`` is. There is no ``code``
    attribute, so no call site can lift one out of a resolution and put it in a country
    filter -- which is the failure AD-5 exists to prevent and F-001 is a record of.
    """


@dataclass(frozen=True, slots=True)
class Country:
    """A benchmark country, identified by the ISO code the export keys country rows on.

    The name is not carried. Two published spellings are one country here, so the name a
    reader used is not the country's identity and holding it would invite a caller to
    filter by it.
    """

    code: str


#: What a surface form can name. Closed, and the two members are not interchangeable:
#: one becomes a filter value, the other becomes a query shape that has no filter.
type CountryIdentity = Country | HomeCountry


@dataclass(frozen=True, slots=True)
class Resolution:
    """What a set of named surface forms resolved to, and what it did not.

    ``unmapped`` is a field rather than a log line: FR-110 says a country value no group
    claims is surfaced with the others, and a resolver that dropped it would be the
    silent failure the refresh report exists to end.
    """

    identities: tuple[CountryIdentity, ...]
    unmapped: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReferenceCountry:
    """One row of the export's country reference table, as the refresh path reads it.

    The published export is the authority on which countries exist and what they are
    called in either language. ``CountryAliases.extended_with()`` takes these rows so the
    packaged table can stay what a steward maintains -- the reviewed *extra* spellings --
    rather than a copy of a reference table that changes without anyone here noticing.
    """

    code: str
    name_en: str
    name_ar: str

    def names(self) -> tuple[str, ...]:
        return tuple(name for name in (self.name_en, self.name_ar) if name.strip())


@dataclass(frozen=True, slots=True)
class CountryAliases:
    """The alias map, indexed for lookup.

    ``groups`` is the table as written, for enumeration and review; ``index`` maps each
    surface form's normal form to a code, and is what ``resolve()`` reads. Both are built
    together by ``build()``, so the index cannot drift from the table it came from.
    """

    home_code: str
    groups: Mapping[str, tuple[str, ...]]
    index: Mapping[str, str]

    @classmethod
    def build(cls, home_code: str, groups: Mapping[str, Sequence[str]]) -> CountryAliases:
        """Index *groups*, refusing a table in which one surface form names two countries.

        The refusal is the point. Two groups claiming a form leaves the resolution to
        whichever was loaded last, which is a country answer decided by file order.
        """
        if home_code not in groups:
            raise CountryAliasError(
                f"{HOME_COUNTRY_RULE} names the code `{home_code}`, which has no group in "
                f"{ALIAS_GROUPS_RULE}; the home country must be in the table it is "
                "excluded from filters by"
            )
        index: dict[str, str] = {}
        held: Mapping[str, tuple[str, ...]] = {
            code: tuple(forms) for code, forms in groups.items()
        }
        for code, forms in held.items():
            if not forms:
                raise CountryAliasError(f"the group for `{code}` lists no surface form")
            for form in forms:
                folded = normalise(form)
                if not folded:
                    raise CountryAliasError(
                        f"the group for `{code}` lists `{form}`, which folds to nothing"
                    )
                owner = index.get(folded)
                if owner is not None and owner != code:
                    raise CountryAliasError(
                        f"`{form}` is claimed by `{code}` and by `{owner}`; a surface form "
                        "names exactly one country, and two claims would leave the answer "
                        "to whichever group was read last"
                    )
                if owner == code:
                    raise CountryAliasError(
                        f"the group for `{code}` lists `{form}` twice; two spellings that "
                        "fold to one normal form are one alias, and the second is noise a "
                        "reviewer has to read past"
                    )
                index[folded] = code
        return cls(home_code=home_code, groups=held, index=index)

    @property
    def codes(self) -> frozenset[str]:
        """Every country the map knows, home country included."""
        return frozenset(self.groups)

    def identity(self, code: str) -> CountryIdentity | None:
        """The identity for an ISO *code*, for the join path that already has one."""
        if code not in self.groups:
            return None
        return HomeCountry() if code == self.home_code else Country(code=code)

    def resolve(self, surface: str) -> CountryIdentity | None:
        """The country *surface* names, or ``None`` when no group claims it.

        ``None`` rather than a guess: a name the map does not know is a country the engine
        cannot answer about, and a nearest match would answer about a different one.
        """
        code = self.index.get(normalise(surface))
        return None if code is None else self.identity(code)

    def resolve_all(self, surfaces: Iterable[str]) -> Resolution:
        """Resolve many names at once, collapsing duplicates and keeping the rest.

        Identities come back in the order they were first named and never twice, so a
        declared set carrying two spellings of one country presents it once. Everything
        unresolved comes back in ``unmapped``, also de-duplicated, for FR-110's report.
        """
        identities: list[CountryIdentity] = []
        unmapped: list[str] = []
        for surface in surfaces:
            found = self.resolve(surface)
            if found is None:
                if surface not in unmapped:
                    unmapped.append(surface)
            elif found not in identities:
                identities.append(found)
        return Resolution(identities=tuple(identities), unmapped=tuple(unmapped))

    def unmapped(self, surfaces: Iterable[str]) -> tuple[str, ...]:
        """The published country values no group claims -- what the refresh report lists."""
        return self.resolve_all(surfaces).unmapped

    def extended_with(self, entries: Iterable[ReferenceCountry]) -> CountryAliases:
        """A map also carrying the names the export's reference table gives each code.

        This is how the home country's Latin-script names reach the map: the export names
        the country, so the packaged table never has to, and the invariant that the name
        appears nowhere under ``src/askai/`` holds without the reader losing the ability
        to name it. A reference name already held by the same code is ignored; one held by
        a different code is refused, because a reference table disagreeing with a reviewed
        group is a fault a steward has to settle rather than a silent overwrite.
        """
        widened = {code: list(forms) for code, forms in self.groups.items()}
        for entry in entries:
            code = entry.code.strip().upper()
            if len(code) != _CODE_LENGTH or not code.isalpha():
                continue
            forms = widened.setdefault(code, [])
            for name in entry.names():
                folded = normalise(name)
                if not folded:
                    continue
                owner = self.index.get(folded)
                if owner is not None and owner != code:
                    raise CountryAliasError(
                        f"the reference table calls `{code}` by the name `{name}`, which "
                        f"the reviewed table gives to `{owner}`"
                    )
                if folded not in {normalise(held) for held in forms}:
                    forms.append(name)
        return CountryAliases.build(self.home_code, widened)


def filter_values(identities: Iterable[CountryIdentity]) -> frozenset[str]:
    """The codes a country filter may carry, from resolved identities.

    The home country cannot appear here, and not because it is filtered out: ``HomeCountry``
    carries no code, so there is nothing to put in the set. A reader who named it is served
    by the national query shape, assembled with the benchmark selection in one place (AD-5).
    """
    return frozenset(one.code for one in identities if isinstance(one, Country))


def _text(rule_set: RuleSet, rule_id: str, key: str) -> str:
    value = rule_set.value(rule_id, key)
    if not isinstance(value, str) or not value.strip():
        raise CountryAliasError(f"{rule_id} value `{key}` must be text, and is {value!r}")
    return value.strip()


def _lines(rule_set: RuleSet, rule_id: str, key: str) -> tuple[str, ...]:
    value = rule_set.value(rule_id, key)
    if not isinstance(value, tuple) or not value:
        raise CountryAliasError(f"{rule_id} value `{key}` must be a non-empty list of groups")
    return value


def _parse_group(line: str) -> tuple[str, tuple[str, ...]]:
    parts = [part.strip() for part in line.split(_SEPARATOR)]
    code, forms = parts[0].upper(), tuple(part for part in parts[1:] if part)
    if len(code) != _CODE_LENGTH or not code.isalpha() or not code.isupper():
        raise CountryAliasError(
            f"`{line}` does not open with an ISO 3166-1 alpha-2 code; a group is "
            f"`CODE {_SEPARATOR} form {_SEPARATOR} form`"
        )
    if not forms:
        raise CountryAliasError(f"the group for `{code}` lists no surface form")
    return code, forms


def load_country_aliases(rule_set: RuleSet | None = None) -> CountryAliases:
    """Build the map from the rule files, or refuse to return one.

    Every failure is a ``CountryAliasError`` naming the group and the constraint it broke,
    for the reason ``loader.py`` gives: a map that loaded partially would resolve some
    countries and silently answer about none of the others.
    """
    source = rules() if rule_set is None else rule_set
    home_code = _text(source, HOME_COUNTRY_RULE, "home_country_code").upper()
    groups: dict[str, Sequence[str]] = {}
    for line in _lines(source, ALIAS_GROUPS_RULE, "groups"):
        code, forms = _parse_group(line)
        if code in groups:
            raise CountryAliasError(
                f"`{code}` opens two groups; one country is one group, so that both "
                "spellings of it are reviewed together"
            )
        groups[code] = forms
    return CountryAliases.build(home_code, groups)


@lru_cache(maxsize=1)
def country_aliases() -> CountryAliases:
    """The packaged map, built once.

    Cached for ``rules()``' reason -- the files are immutable for the life of the process,
    and a lookup on every question must not be a file read on every question. A failure is
    not cached, so a broken table keeps failing rather than failing once and going quiet.
    """
    return load_country_aliases()
