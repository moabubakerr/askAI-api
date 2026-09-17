"""Which composer answers a bound operation -- the routing, in one place.

Purity: pure.

``QuerySpec.operation`` has been a closed set of eleven since Epic 1 and, until this
module, **nothing in the tree branched on it**. Epics 3, 4 and 5 built the composers that
answer ten of them, tested them, and left them unreachable: a grep for ``Operation.``
across ``narrate/``, ``respond/``, ``assemble/`` and ``api/`` returned nothing. The
operation was bound and then dropped on the floor.

This is the branch. It is deliberately a *routing* module and not a composing one: it
imports the composers and hands them what they need, and every sentence a reader sees is
still written by ``assemble/`` from the bilingual catalogue. Nothing here builds an
element, formats a number, or names a ``FormatMode``.

**An operation nothing can answer is stated, never approximated.** ``Unwired`` is the
result for an operation whose composer exists but whose *execution* does not, and the
caller turns it into the refusal the published data cannot answer as asked. That is the
point of returning a value rather than falling through to the value composer: the failure
this replaces is a question about a trend being answered with a single figure, and a
composer wired to the wrong data would be the same failure with more machinery.

**What is wired, and what is not.** ``definition`` is wired end to end: it needs no
figure, so ``GroupsPort`` is the whole of its execution. The other nine need execution
shapes ``execute.value`` does not produce -- it refuses every operation that is not
``value`` before it fetches anything, so a series has no readings, a country comparison
has no per-country rows, and an extremum has no candidate set. Each is ``Unwired`` with
the reason recorded on the value, so the gap is a thing a caller can read rather than a
thing a reviewer has to infer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from askai.assemble.meta.definitions import DefinitionRule, definition_element
from askai.assemble.roles import Placed
from askai.domain.spec import Operation
from askai.messages import Catalogue, Lang
from askai.ports.groups import GroupsPort
from askai.rules import RuleSet

__all__ = ["Composed", "NotHeld", "Request", "Routed", "Unwired", "compose_operation"]


@dataclass(frozen=True, slots=True)
class Composed:
    """The operation was answered, and these are its elements.

    ``rules_fired`` travels with them because the package records it, and the composer
    that fired a rule is the only thing that knows which one -- a list assembled by the
    caller would be a second statement of what happened.
    """

    elements: tuple[Placed, ...]
    rules_fired: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NotHeld:
    """The published layer holds nothing to answer this with -- a stated absence.

    Distinct from ``Unwired``: *"this engine cannot do that"* and *"the catalogue has no
    such row"* are different facts about the world and a reader acts on them differently
    (AD-15). Collapsing them is the failure ``narrate.structured`` already refuses to make
    for a missing figure, and an operation answer gets the same treatment.
    """

    particulars: str


@dataclass(frozen=True, slots=True)
class Unwired:
    """No execution produces what this operation's composer needs.

    ``because`` is an operator-facing statement and never reaches a reader: the reader is
    told, from the bilingual catalogue, that the published data cannot answer the question
    as asked. This is what a maintainer reads when they ask why.
    """

    operation: Operation
    because: str


type Routed = Composed | NotHeld | Unwired


@dataclass(frozen=True, slots=True)
class Request:
    """Everything routing one operation depends on, stated rather than reached for.

    The same shape ``narrate.structured.Answer`` takes, and for the same reason: a
    composer handed its collaborators cannot acquire a different catalogue, a different
    rule set or a different language part-way through an answer.
    """

    operation: Operation
    lang: Lang
    catalogue: Catalogue
    rule_set: RuleSet
    #: The bound detail, or ``None`` when the question bound none.
    detail_id: str | None
    #: What to call the detail to a reader -- its published name where the presentation
    #: layer was consulted, otherwise its id.
    detail_name: str
    #: The catalogue port, when the caller holds one. ``None`` is *"this process was not
    #: wired with one"*, which is an ``Unwired`` and never a silent empty answer.
    groups: GroupsPort | None = None


#: Why each operation that is not wired is not wired. Stated once, here, so the reason a
#: reader gets a refusal is a sentence a maintainer can find -- and so that wiring one is
#: deleting its entry rather than discovering what it needed.
#:
#: Every one of them is the same root cause said ten ways: ``execute.value`` refuses any
#: operation that is not ``value`` before it fetches, so none of these composers has data.
#: Read-only, because a module-level ``dict`` in this engine is the shape an ambient
#: collector takes and ``tests/test_domain_invariants.py`` refuses one.
_NEEDS_EXECUTION: Final[Mapping[Operation, str]] = MappingProxyType({
    Operation.SERIES: (
        "assemble.change.series.series_composition needs the readings of a span; "
        "execute.value refuses a non-value operation before fetching, so it has none"
    ),
    Operation.CHANGE: (
        "assemble.change.delta.change_composition needs a selected or computed Change "
        "over two rows; nothing selects the published change column for a bound spec"
    ),
    Operation.COMPARISON: (
        "assemble.change.compare.compare_periods needs two Figures at two named "
        "periods, and assemble.compare.countries.compare_countries needs one reading "
        "per country; execute.value fetches a single row"
    ),
    Operation.EXTREMUM: (
        "assemble.compare.extrema.extremum needs a candidate set -- every country or "
        "every period in scope, each with its figure; execute.value fetches one"
    ),
    Operation.RANK: (
        "assemble.compare.extrema.ranking needs the same candidate set as extremum, "
        "plus the subject's place in it"
    ),
    Operation.SPREAD: (
        "assemble.compare.extrema.spread needs both ends of a candidate set, and the "
        "two rows the distance was computed from for row_ids"
    ),
    Operation.LIST: (
        "assemble.meta.groups.group_members_element needs a bound Group; compile/ binds "
        "a detail and has no binder for a group name, so nothing resolves the subject"
    ),
    Operation.COUNT: (
        "assemble.meta.groups.group_count_element needs a bound Group, for the same "
        "reason list does; the count is of a group nothing has resolved"
    ),
    Operation.EXPLANATION: (
        "there is no composer: an explanation quotes analyst commentary, and the read "
        "model has no table for it (Story 1.6 creates none, Epic 6 is blocked on it)"
    ),
})


def compose_operation(request: Request) -> Routed:
    """Route *request* to the composer that answers its operation.

    ``value`` never reaches here -- it is the caller's own path and the one this module
    must not change. Exhaustive over the rest: an operation added to the domain fails
    loudly here rather than falling through to a value answer, which is the defect this
    module exists to close.
    """
    match request.operation:
        case Operation.DEFINITION:
            return _definition(request)
        case Operation.VALUE:
            raise ValueError(
                "value is composed by narrate.structured and never routed; reaching here "
                "means the value path was bypassed, which would compose the deployed "
                "answer twice"
            )
        case _:
            because = _NEEDS_EXECUTION.get(request.operation)
            if because is None:
                raise ValueError(
                    f"{request.operation.value} is an Operation this router has not been "
                    "told about; say which composer answers it, or why none can, before "
                    "putting it on a spec -- a fall-through here is a question answered "
                    "with the wrong composer's data"
                )
            return Unwired(operation=request.operation, because=because)


def _definition(request: Request) -> Routed:
    """FR-33: the published definition, quoted and attributed, never generated.

    Three outcomes and they are three different statements. No detail bound, or no
    catalogue port in this process: there is nothing to look the definition up by, and
    that is ``Unwired``. No such detail in the published layer: ``NotHeld``. A detail that
    exists publishes *something*, placeholder included, and ``definition_element`` decides
    whether that something is a definition or the statement that none is published --
    which is its decision and stays its decision (``R-META-PLACEHOLDER-IS-NOT-A-
    DEFINITION`` fires either way, and is recorded either way).
    """
    if request.detail_id is None:
        return Unwired(
            operation=Operation.DEFINITION,
            because="the question bound no detail, so there is no definition to quote",
        )
    if request.groups is None:
        return Unwired(
            operation=Operation.DEFINITION,
            because=(
                "no GroupsPort was supplied; published definitions are read through it, "
                "and this process was not wired with one"
            ),
        )
    published = request.groups.definition(request.detail_id)
    if published is None:
        return NotHeld(
            particulars=(
                f"the published layer holds no detail {request.detail_id}, so there is "
                "no definition to quote and none is composed in its place"
            )
        )
    return Composed(
        elements=(
            definition_element(
                request.catalogue,
                request.lang,
                request.rule_set,
                published,
                request.detail_name,
            ),
        ),
        rules_fired=(DefinitionRule.PLACEHOLDER.value,),
    )
