"""The ``names`` labelled set: questions paired with the detail that answers them.

Purity: IO to load; pure values thereafter.

AD-30 gives retrieval a labelled set and a CI gate of its own, separate from the answer
corpus, because *"the answer corpus asserts on the QuerySpec; it cannot tell whether the
right passage came back."* For this collection the ground truth is **free from the
findings** -- finding 42's Arabic morphology, F-014's paraphrases and F-003's fifteen
GDP candidates are already question-to-detail pairs -- and the set on disk is those,
written out and grounded in the published export.

Three properties of the shape below are the ones the measurement rests on:

**A pair may name several details, and that is not a weakness.** The export publishes
eight details named *Sector Contribution To GDP* and two named *Global Cybersecurity
Index (GCI) Rank*. A reader typing either has not said which they mean, and neither can
any index: every one of those surfaces scores identically. Labelling one arbitrary
member as *the* answer would report a one-in-eight accident as a retrieval failure and
would make a derived floor look worse than the retrieval actually is. So the expectation
is a **set**, and a case is satisfied by any member of it.

**A pair may name no detail at all.** AD-30 is explicit that recall alone *"would reward
a system that always returns its nearest neighbour"*, and the negative cases are the only
evidence in the set about how low a floor may go. Without them every threshold above zero
costs recall and buys nothing measurable, so a floor derived from positives alone would
always derive to zero.

**The set is versioned, and the version travels with anything derived from it.** A floor
in ``rules/`` records the version it came from (:mod:`askai.adapters.index.floors`); a
recorded version that is not this one means the distributions moved underneath the value
and the build fails rather than answering against a stale number.

**The format, and why it is not YAML.** Everything in this package is held to the
standard library plus this project -- NFR-4, asserted by a scan in ``tests/test_index.py``
-- and a YAML library is neither. So a set is a directory of plain text: ``#`` starts a
comment, ``[case-id]`` opens a case, and ``key: value`` lines fill it in until the next
one. It is a format small enough to specify in a paragraph and parse in forty lines, and
a labelled set is read by people at least as often as by this module.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from askai.messages.lang import Lang

__all__ = [
    "CASE_SUFFIX",
    "SET_FILE",
    "LabelKind",
    "LabelledCase",
    "LabelledSet",
    "LabelledSetError",
    "load_labelled_set",
]

#: The manifest inside a labelled-set directory: the set's name, version and date.
SET_FILE: Final = "set.txt"

#: Every other file of this suffix beside it is a file of cases, so adding pairs is
#: adding a file rather than editing a list of files a reviewer must keep in step.
CASE_SUFFIX: Final = ".cases"

_COMMENT: Final = "#"
_OPEN: Final = "["
_CLOSE: Final = "]"
_SEPARATOR: Final = ":"
_EXPECT_SEPARATOR: Final = ","
_FIELDS: Final = ("lang", "kind", "question", "expect", "why")


class LabelledSetError(RuntimeError):
    """A labelled set is missing, malformed, or contradicts itself.

    Raised rather than skipped. A measurement taken over a set that silently lost half
    its negative cases reports a separation that was never there, and there is nothing
    downstream that could notice -- which is the same argument ``IndexLoadError`` makes
    about a generation built by another vector source.
    """


class LabelKind(StrEnum):
    """What kind of naming a case exercises.

    Kept on every case because the aggregate numbers are uninteresting without it: a
    vectoriser that scores well overall by winning every exact match and losing every
    paraphrase is the one this collection already has, and only the breakdown says so.
    """

    #: The reader typed a published surface, or all but typed it.
    EXACT = "exact"

    #: A whole question in the reader's own words, naming the same measurable.
    PARAPHRASE = "paraphrase"

    #: The reader's word and the published word mean the same and share no characters --
    #: non-oil for non-hydrocarbon, hospitality for tourism.
    SYNONYM = "synonym"

    #: A misspelling of a published surface.
    TYPO = "typo"

    #: A fragment of one published surface, identifying it unambiguously.
    PARTIAL = "partial"

    #: A name the export publishes on several details, which a reader typing it has not
    #: chosen between. Satisfied by any of them; see this module's docstring.
    AMBIGUOUS = "ambiguous"

    #: A question this corpus holds no answer to. The correct result is an empty one.
    NONE = "none"


@dataclass(frozen=True, slots=True)
class LabelledCase:
    """One question, and the detail or details that genuinely answer it."""

    case_id: str
    lang: Lang
    kind: LabelKind
    question: str
    expected: frozenset[str]
    why: str

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise LabelledSetError(f"{self.case_id}: a case carries a question")
        if not self.why.strip():
            raise LabelledSetError(
                f"{self.case_id}: a case records why it is evidence; a pair nobody can "
                "check against the export is a pair that quietly stops being true"
            )
        if self.is_negative and self.expected:
            raise LabelledSetError(
                f"{self.case_id}: is labelled `none` and names {len(self.expected)} "
                "details; the kind and the expectation cannot disagree"
            )
        if not self.is_negative and not self.expected:
            raise LabelledSetError(
                f"{self.case_id}: names no detail but is not labelled `none`; a case with "
                "no expectation is a negative case and must say so"
            )

    @property
    def is_negative(self) -> bool:
        """Whether the correct result for this case is an empty one."""
        return self.kind is LabelKind.NONE


@dataclass(frozen=True, slots=True)
class LabelledSet:
    """A whole labelled set: its identity, and its cases in file then written order."""

    name: str
    version: int
    built_at: str
    cases: tuple[LabelledCase, ...]

    def __iter__(self) -> Iterator[LabelledCase]:
        return iter(self.cases)

    def __len__(self) -> int:
        return len(self.cases)

    @property
    def identity(self) -> str:
        """``<name>-v<version>`` -- what a derived value records to say where it came from.

        One string rather than two fields, because a floor carrying the name and the
        version in separate clauses can be half-updated, and half-updated is exactly the
        state AD-30's staleness check exists to catch.
        """
        return f"{self.name}-v{self.version}"

    @property
    def positives(self) -> tuple[LabelledCase, ...]:
        return tuple(case for case in self.cases if not case.is_negative)

    @property
    def negatives(self) -> tuple[LabelledCase, ...]:
        return tuple(case for case in self.cases if case.is_negative)

    def by_kind(self, kind: LabelKind) -> tuple[LabelledCase, ...]:
        return tuple(case for case in self.cases if case.kind is kind)

    def expected_details(self) -> frozenset[str]:
        """Every detail id any case names. Checked against the export by the harness."""
        return frozenset(detail for case in self.cases for detail in case.expected)


def _lines(path: Path) -> Iterable[tuple[int, str]]:
    """Every meaningful line of *path*, with its number and without its comments."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise LabelledSetError(f"{path}: cannot be read -- {error}") from error
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if line and not line.startswith(_COMMENT):
            yield number, line


def _pair(line: str, where: str) -> tuple[str, str]:
    key, separator, value = line.partition(_SEPARATOR)
    if not separator:
        raise LabelledSetError(
            f"{where}: {line!r} is neither a [case-id] nor a `key: value` line"
        )
    return key.strip(), value.strip()


def _member[MemberT: StrEnum](enum: type[MemberT], raw: str, key: str, where: str) -> MemberT:
    try:
        return enum(raw)
    except ValueError as error:
        known = ", ".join(member.value for member in enum)
        raise LabelledSetError(f"{where}: `{key}` is {raw!r}; it is one of {known}") from error


def _expected(raw: str, where: str) -> frozenset[str]:
    details = [part.strip() for part in raw.split(_EXPECT_SEPARATOR) if part.strip()]
    if len(set(details)) != len(details):
        raise LabelledSetError(f"{where}: `expect` names the same detail twice")
    return frozenset(details)


def _case(case_id: str, fields: dict[str, str], where: str) -> LabelledCase:
    missing = [field for field in _FIELDS if field not in fields]
    if missing:
        raise LabelledSetError(
            f"{where}: {case_id} is missing {missing}; a case states all of {list(_FIELDS)} "
            "so that a field left out is a failure rather than a silent default"
        )
    return LabelledCase(
        case_id=case_id,
        lang=_member(Lang, fields["lang"], "lang", where),
        kind=_member(LabelKind, fields["kind"], "kind", where),
        question=fields["question"],
        expected=_expected(fields["expect"], where),
        why=fields["why"],
    )


def _cases_in(path: Path) -> list[LabelledCase]:
    cases: list[LabelledCase] = []
    case_id = ""
    fields: dict[str, str] = {}
    for number, line in _lines(path):
        where = f"{path.name}:{number}"
        if line.startswith(_OPEN) and line.endswith(_CLOSE):
            if case_id:
                cases.append(_case(case_id, fields, where))
            case_id, fields = line[1:-1].strip(), {}
            if not case_id:
                raise LabelledSetError(f"{where}: a case opens with its id in brackets")
            continue
        if not case_id:
            raise LabelledSetError(f"{where}: {line!r} comes before any [case-id]")
        key, value = _pair(line, where)
        if key not in _FIELDS:
            raise LabelledSetError(
                f"{where}: {case_id} carries `{key}`, which is not one of {list(_FIELDS)}; "
                "a misspelled key is how a case stops asserting what its author meant"
            )
        if key in fields:
            raise LabelledSetError(f"{where}: {case_id} states `{key}` twice")
        fields[key] = value
    if case_id:
        cases.append(_case(case_id, fields, path.name))
    if not cases:
        raise LabelledSetError(
            f"{path}: holds no cases; a case file that was meant to carry evidence and "
            "does not is worse than one that is absent"
        )
    return cases


def _manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise LabelledSetError(
            f"{path} does not exist; a labelled set is a directory holding a {SET_FILE} "
            f"manifest beside its {CASE_SUFFIX} files"
        )
    return {key: value for _, line in _lines(path) for key, value in (_pair(line, str(path)),)}


def _version(manifest: dict[str, str], path: Path) -> int:
    raw = manifest.get("version", "")
    if not raw.isdigit() or int(raw) < 1:
        raise LabelledSetError(
            f"{path}: `version` is {raw!r}; a labelled set is versioned with a whole "
            "number from 1, and anything derived from it records which one"
        )
    return int(raw)


def _named(manifest: dict[str, str], key: str, path: Path) -> str:
    value = manifest.get(key, "")
    if not value:
        raise LabelledSetError(f"{path}: `{key}` is missing")
    return value


def load_labelled_set(directory: Path) -> LabelledSet:
    """Read the labelled set in *directory*, or refuse to return one.

    The directory holds a ``set.txt`` manifest -- name, version, provenance -- and one or
    more sibling ``*.cases`` files. Every failure is a raised ``LabelledSetError`` naming
    the file and the line, because the alternative is a measurement taken over fewer pairs
    than the author believes exist, reported as a number with no warning attached.
    """
    manifest_path = directory / SET_FILE
    manifest = _manifest(manifest_path)
    cases: list[LabelledCase] = []
    for path in sorted(directory.glob(f"*{CASE_SUFFIX}")):
        cases.extend(_cases_in(path))
    if not cases:
        raise LabelledSetError(f"{directory}: holds a manifest and no cases")
    _refuse_duplicate_ids(cases, directory)
    return LabelledSet(
        name=_named(manifest, "set", manifest_path),
        version=_version(manifest, manifest_path),
        built_at=_named(manifest, "built_at", manifest_path),
        cases=tuple(cases),
    )


def _refuse_duplicate_ids(cases: Sequence[LabelledCase], directory: Path) -> None:
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise LabelledSetError(
                f"{directory}: {case.case_id} appears twice; a case id names one pair so "
                "that a regression can be cited by it"
            )
        seen.add(case.case_id)
