"""The rule schema -- one shape, owned here, shared by every file under ``data/``.

Purity: pure, validates data it is handed.

AD-11 says grain selection, the latest-value definition, rounding and display format
live in versioned data files rather than in code. That only pays if the files answer to
*one* schema: a schema invented per file is a second place for the logic to live, and
the first malformed file would be malformed against nothing.

So the whole of the rule shape is here, and every constraint that can be a schema
constraint is one. Three of them are worth saying out loud:

**``status`` has no default.** The catalogue (``docs/RULES.md`` v2.1) records a status
for all 188 of its rules -- 187 ``proposed``, 1 ``rejected``, and **0 ``agreed``**. A
default would manufacture agreement that nobody gave, which is the exact failure FR-72a
exists to prevent. A file that omits the field fails to load.

**Nothing here gates on status.** ``agreed`` and ``proposed`` load identically and fire
identically, so moving a rule to ``agreed`` is a data edit and not a code change; the
gate that consumes the status is Story 10.7. The single asymmetry is ``rejected``, which
loads (so it is not re-proposed) and never fires -- enforced in ``loader.py``, not here.

**A ``rejected`` rule must say why it was withdrawn.** ``R-157`` is in the catalogue
because it was tried, fixed one case and broke twenty-two checks; an entry recording the
withdrawal without recording the reason would be re-proposed within the year, which is
the only thing the entry exists to prevent.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from askai.domain.period import Grain

__all__ = [
    "RULE_ID_PATTERN",
    "Rule",
    "RuleFile",
    "RuleKind",
    "RuleStatus",
    "RuleValue",
]

#: ``R-<AREA>-<SLUG>``. Upper case, digits and single hyphens, with the area as the
#: first segment and the slug as everything after it -- so an id carries where the rule
#: lives as well as which rule it is, and a file cannot claim a rule from another area.
#: Ids are stable and never reused; a withdrawn rule keeps its id (see ``R-157``).
RULE_ID_PATTERN: Final = re.compile(
    r"R-(?P<area>[A-Z][A-Z0-9]*)-(?P<slug>[A-Z0-9]+(?:-[A-Z0-9]+)*)"
)

#: What a clause may carry. Deliberately narrow: a rule holds published constants,
#: toggles and reviewed lookups (the catalogue's `constant`, `switch` and `table`
#: kinds), never an expression to be evaluated. Anything needing more than this is a
#: code path and, per AD-11, needs a recorded reason to exist.
type RuleValue = bool | int | str | tuple[str, ...] | Mapping[str, int]

_GRAIN_NAMES: Final = frozenset(grain.value for grain in Grain)


class RuleStatus(StrEnum):
    """Where a rule stands with the person who has standing to agree it.

    The three the catalogue uses, and no fourth. ``agreed`` is currently unreachable in
    practice -- nobody holds the pen (FR-72a) -- but it is in the schema from the first
    day so that the day someone does, the move is a one-word data edit.
    """

    AGREED = "agreed"
    PROPOSED = "proposed"
    REJECTED = "rejected"


class RuleKind(StrEnum):
    """The catalogue's own taxonomy of what a rule *is* (``docs/RULES.md`` §2).

    Only the three data kinds may carry clauses; the rest are here so a rule authored
    from the catalogue keeps the classification it arrived with rather than losing it at
    the boundary.
    """

    CONSTANT = "constant"
    SWITCH = "switch"
    TABLE = "table"
    CODE = "code"
    WORDING = "wording"
    PRINCIPLE = "principle"


class Rule(BaseModel):
    """One rule, as a reader of ``rules/`` sees it.

    ``extra="forbid"`` is the load-bearing setting: a misspelled key is the way a rule
    silently stops carrying what its author thought it carried, and a schema that
    ignores unknown keys turns that into a wrong answer rather than a failed start.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    # Anchored explicitly: pydantic's `pattern` is a search, not a full match, so an
    # unanchored form would accept `see rule R-GRAIN-TIE for why` as an id.
    id: Annotated[str, Field(pattern=rf"^{RULE_ID_PATTERN.pattern}$")]
    statement: Annotated[str, Field(min_length=20)]
    status: RuleStatus
    kind: RuleKind
    sources: Annotated[Sequence[str], Field(min_length=1)]
    catalogue: Sequence[str] = ()
    values: Mapping[str, RuleValue] = {}
    note: str | None = None
    withdrawn_because: str | None = None

    @property
    def area(self) -> str:
        """The ``<AREA>`` segment of the id, split out of the id rather than repeated."""
        match = RULE_ID_PATTERN.fullmatch(self.id)
        if match is None:  # pragma: no cover -- the field pattern has already refused it
            raise ValueError(f"{self.id} is not a rule id of the form R-<AREA>-<SLUG>")
        return match.group("area")

    @property
    def is_fireable(self) -> bool:
        """May the engine act on this rule?

        ``agreed`` and ``proposed`` are both yes, and that is the point: status is
        recorded, not gated. Only ``rejected`` is no.
        """
        return self.status is not RuleStatus.REJECTED

    @model_validator(mode="after")
    def _withdrawal_is_explained(self) -> Self:
        if self.status is RuleStatus.REJECTED and not (self.withdrawn_because or "").strip():
            raise ValueError(
                f"{self.id} is rejected and must say why in `withdrawn_because`; a "
                "withdrawal with no recorded reason is re-proposed within the year, "
                "which is the only thing the entry exists to prevent"
            )
        if self.status is not RuleStatus.REJECTED and self.withdrawn_because is not None:
            raise ValueError(
                f"{self.id} is {self.status.value} and carries `withdrawn_because`; a "
                "rule is withdrawn or it is not, and the reason belongs to the rejection"
            )
        return self

    @model_validator(mode="after")
    def _clauses_belong_to_data_kinds(self) -> Self:
        data_kinds = {RuleKind.CONSTANT, RuleKind.SWITCH, RuleKind.TABLE}
        if self.values and self.kind not in data_kinds:
            kinds = ", ".join(sorted(kind.value for kind in data_kinds))
            raise ValueError(
                f"{self.id} is kind `{self.kind.value}` and carries values; only "
                f"{kinds} rules hold values the engine reads"
            )
        return self

    @model_validator(mode="after")
    def _grain_tables_name_every_grain(self) -> Self:
        """A lookup keyed by grain covers all of them, or none of them.

        A window table holding ``monthly`` and ``yearly`` does not fail -- it falls
        through to whatever the caller does when the key is missing, which is a
        reader-affecting constant living in code again. Partial coverage is the shape of
        that defect, so it is rejected here.
        """
        for key, value in self.values.items():
            if not isinstance(value, Mapping):
                continue
            keys = frozenset(value)
            if not keys & _GRAIN_NAMES:
                continue
            if keys != _GRAIN_NAMES:
                missing = ", ".join(sorted(_GRAIN_NAMES - keys)) or "nothing"
                extra = ", ".join(sorted(keys - _GRAIN_NAMES)) or "nothing"
                raise ValueError(
                    f"{self.id} value `{key}` is keyed by grain and is incomplete: "
                    f"missing {missing}; not a grain: {extra}"
                )
        return self


class RuleFile(BaseModel):
    """One ``*.yaml`` under ``data/`` -- an area, and the rules that belong to it.

    The area is declared once at the top of the file rather than inferred from the
    filename, so renaming a file cannot silently move a rule into another area, and
    every id in the file is checked against it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    area: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9]*$")]
    about: Annotated[str, Field(min_length=10)]
    rules: Annotated[Sequence[Rule], Field(min_length=1)]

    @model_validator(mode="after")
    def _ids_belong_to_this_area_and_are_unique(self) -> Self:
        seen: set[str] = set()
        for rule in self.rules:
            if rule.area != self.area:
                raise ValueError(
                    f"{rule.id} is in the `{self.area}` file but names area "
                    f"`{rule.area}`; a rule id carries where the rule lives"
                )
            if rule.id in seen:
                raise ValueError(f"{rule.id} appears twice; rule ids are stable and never reused")
            seen.add(rule.id)
        return self
