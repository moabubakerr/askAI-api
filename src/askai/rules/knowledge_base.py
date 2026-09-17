"""The knowledge base: what an approved answer may be made of, read from the rule table.

Purity: reads the packaged rule files once; pure thereafter.

FR-77 enumerates the admission set and FR-79 closes the world around it. Both are the
kind of claim that decays into folklore unless something reads it: a comment saying
"these are the only sources" is true on the day it is written and silently false the day
a story adds a table. So the set is a reviewable table in ``data/knowledge-base.yaml``
and this module is its only parser -- the same arrangement ``countries.py`` has with the
alias map, and for the same reason.

**The admission list is enumerated, not derived.** It would be easy to build the set by
listing the read model's tables, and that would assert nothing at all: every table would
be admitted because it exists. The list is written by hand and the *read model* is
checked against it, so the failure arrives when a new table is created rather than when
someone later notices it was never approved.

**A source may be admitted and not yet materialised.** Four of the nine lines carry no
table: analyst prose has no table (Story 1.6 created none), articles are loose export
files no story has ingested, and groups are read from the published benchmark tables.
Carrying them as ``table=None`` records the admission decision without pretending the
storage exists, which is the difference between an enumeration and a wish list.

**Exported is not publishable.** :class:`ArticleAdmission` holds the publication
predicate as four named flags rather than as a ``WHERE`` clause someone copies, so the
question "what does published mean for this source" has one answer a steward can read.
The measured counts travel with it -- 67 of 84 -- so the test that applies the predicate
to the real export is checking a number the rule file committed to, not a number it
derived from the same rows it is testing.

Every failure here is a :class:`KnowledgeBaseError`, raised, never defaulted: a knowledge
base that loaded partially would admit some sources and silently admit nothing about the
rest, which is the closed world failing open.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from askai.rules.loader import RuleLoadError, RuleSet, rules

__all__ = [
    "ADMITTED_SOURCES_RULE",
    "ARTICLE_ADMISSION_RULE",
    "OUTBOUND_INVENTORY_RULE",
    "REFUSAL_CAUSES_RULE",
    "AdmittedRefusal",
    "AdmittedSource",
    "ArticleAdmission",
    "KnowledgeBase",
    "KnowledgeBaseError",
    "OutboundInventory",
    "knowledge_base",
    "load_knowledge_base",
]

#: The four rules this module reads. Named here so a rename in the data file fails at
#: startup with a message naming the rule, rather than admitting nothing and answering
#: from an empty knowledge base that looks exactly like a closed one.
ADMITTED_SOURCES_RULE: Final = "R-KB-ADMITTED-SOURCES"
ARTICLE_ADMISSION_RULE: Final = "R-KB-ARTICLE-ADMISSION"
OUTBOUND_INVENTORY_RULE: Final = "R-KB-OUTBOUND-INVENTORY"
REFUSAL_CAUSES_RULE: Final = "R-KB-REFUSAL-CAUSES"

#: A line is `field | field | ...`. A file format, not a rule: it decides nothing a
#: reader of an answer sees, and changing it changes no behaviour.
_SEPARATOR: Final = "|"

#: What a line writes where a table, or a discovering stage, does not exist yet.
_NONE: Final = "-"

_SOURCE_FIELDS: Final = 3
_REFUSAL_FIELDS: Final = 2


class KnowledgeBaseError(RuleLoadError):
    """The knowledge base table is missing, malformed, or admits something twice.

    A subclass of ``RuleLoadError`` because it is the same failure at the same moment:
    the engine does not start without knowing what it is allowed to answer from, and an
    operator who catches rule-load failures catches this one too.
    """


@dataclass(frozen=True, slots=True)
class AdmittedSource:
    """One admitted source: its key, the table it materialises as, and what it is.

    ``table`` is ``None`` rather than an empty string so that "not stored anywhere" is a
    state a caller has to name, instead of a falsy value it can pass to a query builder.
    """

    key: str
    table: str | None
    about: str


@dataclass(frozen=True, slots=True)
class ArticleAdmission:
    """The publication predicate for articles, and the counts it was measured at.

    Four flags, not one: FR-77a's point is that ``Published`` alone admits rows that are
    inactive, deleted or still drafts. Holding all four -- including the one that
    discriminates nothing in today's export -- is what keeps the predicate correct on the
    day a draft is exported.
    """

    required_true: tuple[str, ...]
    required_false: tuple[str, ...]
    exported: int
    admitted: int

    def admits(self, flags: Mapping[str, bool]) -> bool:
        """Whether a row carrying *flags* is a source.

        A flag the row does not carry is a row this predicate cannot judge, so it is not
        admitted. Defaulting a missing flag to its permissive value is how an export that
        quietly dropped a column would start admitting everything.
        """
        return all(flags.get(name, False) for name in self.required_true) and not any(
            flags.get(name, True) for name in self.required_false
        )


@dataclass(frozen=True, slots=True)
class OutboundInventory:
    """Where a call may leave the process, and where it may not.

    The inventory is the evidence for NFR-4a. It is held as data for the same reason the
    admission set is: "the engine makes no outbound call at answer time" is a property
    that has to be re-checked on every commit, and a property nothing reads is a comment.
    """

    network_libraries: frozenset[str]
    answer_path_packages: tuple[str, ...]
    estate_holders: tuple[str, ...]

    def is_network_library(self, imported: str) -> bool:
        """Whether *imported* -- a dotted module name -- is a way out of the process."""
        return imported.split(".")[0] in self.network_libraries

    def inside_the_estate(self, module_path: str) -> bool:
        """Whether *module_path*, relative to ``src/askai`` and posix-spelled, may hold one."""
        return any(module_path.startswith(f"{holder}/") for holder in self.estate_holders)


@dataclass(frozen=True, slots=True)
class AdmittedRefusal:
    """One of the six causes a refusal may carry, and the stage that discovers it.

    ``discovered_by`` is the value of a ``compile.resolve.RefusalCause`` member, as a
    string: ``rules/`` may not import ``compile/``, and a cause is a code either way. It
    is ``None`` for the three causes no stage discovers yet -- recorded rather than
    omitted, because an enumeration that lists only what is built cannot be the thing the
    unbuilt half is checked against.
    """

    code: str
    discovered_by: str | None


@dataclass(frozen=True, slots=True)
class KnowledgeBase:
    """The admission set, the publication predicate, the inventory and the six causes."""

    sources: tuple[AdmittedSource, ...]
    articles: ArticleAdmission
    outbound: OutboundInventory
    refusals: tuple[AdmittedRefusal, ...]

    @property
    def keys(self) -> frozenset[str]:
        """Every admitted source key."""
        return frozenset(source.key for source in self.sources)

    @property
    def tables(self) -> frozenset[str]:
        """Every read model table an admitted source materialises as.

        The set a table is checked for membership of. A table absent from it is a source
        nobody admitted, which is a gate failure and not a lookup miss.
        """
        return frozenset(source.table for source in self.sources if source.table is not None)

    @property
    def refusal_codes(self) -> tuple[str, ...]:
        """The six machine codes, in the order the table writes them."""
        return tuple(refusal.code for refusal in self.refusals)

    @property
    def discoverers(self) -> frozenset[str]:
        """The resolution outcomes the table binds to a cause."""
        return frozenset(
            refusal.discovered_by
            for refusal in self.refusals
            if refusal.discovered_by is not None
        )

    def admits_table(self, table: str) -> bool:
        """Whether *table* is the materialisation of an admitted source."""
        return table in self.tables

    def source(self, key: str) -> AdmittedSource:
        """The admitted source named *key*, or raise naming what is admitted."""
        for source in self.sources:
            if source.key == key:
                return source
        admitted = ", ".join(sorted(self.keys))
        raise LookupError(f"`{key}` is not an admitted source; the set is: {admitted}")


def _lines(rule_set: RuleSet, rule_id: str, key: str) -> tuple[str, ...]:
    value = rule_set.value(rule_id, key)
    if not isinstance(value, tuple) or not value:
        raise KnowledgeBaseError(f"{rule_id} value `{key}` must be a non-empty list of lines")
    return value


def _counts(rule_set: RuleSet, rule_id: str, key: str) -> Mapping[str, int]:
    value = rule_set.value(rule_id, key)
    if not isinstance(value, Mapping):
        raise KnowledgeBaseError(f"{rule_id} value `{key}` must be a mapping of name to count")
    return value


def _count(counts: Mapping[str, int], rule_id: str, name: str) -> int:
    try:
        return counts[name]
    except KeyError:
        raise KnowledgeBaseError(f"{rule_id} counts do not name `{name}`") from None


def _fields(line: str, rule_id: str, expected: int) -> Sequence[str]:
    parts = [part.strip() for part in line.split(_SEPARATOR)]
    if len(parts) != expected or not all(parts):
        shape = f" {_SEPARATOR} ".join(f"field{index + 1}" for index in range(expected))
        raise KnowledgeBaseError(
            f"{rule_id}: `{line}` is not a line of {expected} fields -- a line is `{shape}`"
        )
    return parts


def _optional(field: str) -> str | None:
    return None if field == _NONE else field


def _sources(rule_set: RuleSet) -> tuple[AdmittedSource, ...]:
    admitted: list[AdmittedSource] = []
    keys: set[str] = set()
    tables: dict[str, str] = {}
    for line in _lines(rule_set, ADMITTED_SOURCES_RULE, "sources"):
        key, table, about = _fields(line, ADMITTED_SOURCES_RULE, _SOURCE_FIELDS)
        if key in keys:
            raise KnowledgeBaseError(
                f"{ADMITTED_SOURCES_RULE}: `{key}` is admitted twice; one source is one "
                "line, so that a reviewer reads the whole of what it admits in one place"
            )
        keys.add(key)
        materialised = _optional(table)
        if materialised is not None:
            owner = tables.get(materialised)
            if owner is not None:
                raise KnowledgeBaseError(
                    f"{ADMITTED_SOURCES_RULE}: `{materialised}` is claimed by `{key}` and "
                    f"by `{owner}`; a table is the materialisation of one admitted source"
                )
            tables[materialised] = key
        admitted.append(AdmittedSource(key=key, table=materialised, about=about))
    return tuple(admitted)


def _articles(rule_set: RuleSet) -> ArticleAdmission:
    counts = _counts(rule_set, ARTICLE_ADMISSION_RULE, "counts")
    exported = _count(counts, ARTICLE_ADMISSION_RULE, "exported")
    admitted = _count(counts, ARTICLE_ADMISSION_RULE, "admitted")
    if not 0 <= admitted <= exported:
        raise KnowledgeBaseError(
            f"{ARTICLE_ADMISSION_RULE} admits {admitted} of {exported} exported articles; "
            "the admitted set is a subset of the exported one"
        )
    return ArticleAdmission(
        required_true=_lines(rule_set, ARTICLE_ADMISSION_RULE, "required_true"),
        required_false=_lines(rule_set, ARTICLE_ADMISSION_RULE, "required_false"),
        exported=exported,
        admitted=admitted,
    )


def _outbound(rule_set: RuleSet) -> OutboundInventory:
    return OutboundInventory(
        network_libraries=frozenset(_lines(rule_set, OUTBOUND_INVENTORY_RULE, "network_libraries")),
        answer_path_packages=_lines(rule_set, OUTBOUND_INVENTORY_RULE, "answer_path_packages"),
        estate_holders=_lines(rule_set, OUTBOUND_INVENTORY_RULE, "estate_holders"),
    )


def _refusals(rule_set: RuleSet) -> tuple[AdmittedRefusal, ...]:
    admitted: list[AdmittedRefusal] = []
    codes: set[str] = set()
    discoverers: dict[str, str] = {}
    for line in _lines(rule_set, REFUSAL_CAUSES_RULE, "causes"):
        code, stage = _fields(line, REFUSAL_CAUSES_RULE, _REFUSAL_FIELDS)
        if code in codes:
            raise KnowledgeBaseError(
                f"{REFUSAL_CAUSES_RULE}: `{code}` is listed twice; a refusal cause is one "
                "line, and two would be two phrasings of one gap"
            )
        codes.add(code)
        discovered_by = _optional(stage)
        if discovered_by is not None:
            owner = discoverers.get(discovered_by)
            if owner is not None:
                raise KnowledgeBaseError(
                    f"{REFUSAL_CAUSES_RULE}: `{discovered_by}` discovers `{code}` and "
                    f"`{owner}`; one resolution outcome is one cause, or the reader is "
                    "told two different things about one refusal"
                )
            discoverers[discovered_by] = code
        admitted.append(AdmittedRefusal(code=code, discovered_by=discovered_by))
    return tuple(admitted)


def load_knowledge_base(rule_set: RuleSet | None = None) -> KnowledgeBase:
    """Build the knowledge base from the rule files, or refuse to return one.

    Every failure is a ``KnowledgeBaseError`` naming the rule and the constraint it broke,
    for ``loader.py``'s reason: an admission set that loaded partially would admit some
    sources and quietly admit nothing about the rest, and an engine that admits nothing
    is indistinguishable -- from the outside -- from one that is correctly closed.
    """
    source = rules() if rule_set is None else rule_set
    return KnowledgeBase(
        sources=_sources(source),
        articles=_articles(source),
        outbound=_outbound(source),
        refusals=_refusals(source),
    )


@lru_cache(maxsize=1)
def knowledge_base() -> KnowledgeBase:
    """The packaged knowledge base, built once.

    Cached for ``rules()``' reason -- the files are immutable for the life of the process,
    and an admission check on every answer must not be a file read on every answer. A
    failure is not cached, so a broken table keeps failing rather than failing once.
    """
    return load_knowledge_base()
