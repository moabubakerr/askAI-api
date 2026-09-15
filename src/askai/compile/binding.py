"""How a field was bound, recorded beside the spec that carries what it was bound to.

Purity: pure.

AD-19 asks for two things a ``QuerySpec`` cannot say about itself: that **exactly one
binder owns each field**, and **how** each field was bound. The spec is deliberately the
answer and nothing else -- it has no provenance fields and this story does not add any --
so the record lives here, on the artifact that carries the spec out of ``compile/``.

Two axes, because the acceptance criteria ask for two different things:

``Precedence`` is AD-19's ladder -- what the value came from: the question, the history,
the rule default, or nothing. ``BoundBy`` is FR-14's question -- whose authority it was:
the reader, a rule, a semantic match, or a model. They are not the same axis. A value
inherited from an earlier turn came from the *history* by precedence and from the
*reader* by authority, and collapsing them would lose whichever half was collapsed.

In this epic ``SEMANTIC`` and ``MODEL`` never appear: nothing here searches an index and
nothing here calls a model. They are in the closed set from the first day so that the
epic that adds one records it, rather than discovering it needs somewhere to record it.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from enum import StrEnum

from askai.domain.spec import Bound, Deferred, FieldState, QuerySpec, Unbound

__all__ = [
    "Binding",
    "BoundBy",
    "CompiledQuestion",
    "Precedence",
    "SpecField",
    "UnboundReason",
    "bindable_fields",
    "unbound",
]


class SpecField(StrEnum):
    """The ``QuerySpec`` fields a binder owns.

    ``today`` and ``spec_version`` are absent because neither is bound: ``today`` is an
    input to compiling and ``spec_version`` is the shape of the artifact. A test asserts
    this set is exactly the spec's bindable fields, so a field added to the spec without
    a binder fails rather than quietly defaulting.
    """

    DETAIL = "detail"
    PERIOD = "period"
    COUNTRY_SCOPE = "country_scope"
    MEASURE = "measure"
    OPERATION = "operation"


class Precedence(StrEnum):
    """AD-19's ladder. The order of the members is the order the binders walk it, and
    ``R-BIND-PRECEDENCE`` states the same order as data; a test asserts the two agree."""

    NAMED_IN_QUESTION = "named-in-question"
    INHERITED_FROM_HISTORY = "inherited-from-history"
    RULE_DEFAULT = "rule-default"
    UNBOUND = "unbound"


class BoundBy(StrEnum):
    """Whose authority the value carries (FR-14)."""

    READER = "reader"
    RULE = "rule"
    SEMANTIC = "semantic"
    MODEL = "model"


class UnboundReason(StrEnum):
    """Why a field could not be bound -- a closed set, never a sentence.

    ``Unbound(reason)`` is what a clarification or a refusal is composed from, and
    composing reader-facing text is ``narrate/``'s job from the bilingual catalogue. A
    code keeps the cause exact and keeps English prose out of a layer that must be able
    to answer in either language.
    """

    NO_DETAIL_NAMED = "no-detail-named"
    DETAIL_NAME_IS_SHARED = "detail-name-is-shared"
    GRAIN_NOT_PUBLISHED = "grain-not-published"
    MORE_THAN_ONE_PERIOD_NAMED = "more-than-one-period-named"
    PERIOD_RANGE_RUNS_BACKWARDS = "period-range-runs-backwards"


def unbound(reason: UnboundReason, particulars: str) -> Unbound:
    """An ``Unbound`` carrying its cause as a code, with the particulars after it."""
    return Unbound(reason=f"{reason.value}: {particulars}")


@dataclass(frozen=True, slots=True)
class Binding:
    """One field, and the single binder's account of how it reached its value."""

    field: SpecField
    precedence: Precedence
    bound_by: BoundBy | None

    def __post_init__(self) -> None:
        # An unbound field was not bound by anybody, and a bound one was. Letting either
        # half drift would make the record a label rather than an account.
        if (self.bound_by is None) is not (self.precedence is Precedence.UNBOUND):
            raise ValueError(
                f"{self.field.value} is {self.precedence.value} and bound_by "
                f"{self.bound_by}; a field is bound by someone or it is unbound"
            )


@dataclass(frozen=True, slots=True)
class CompiledQuestion:
    """The frozen spec, and the account of how each of its fields was bound.

    This is what leaves ``compile/``. Nothing past here may set, widen or reinterpret a
    field (AD-1): the spec is frozen, and the account is what makes "bound exactly once"
    checkable rather than asserted.
    """

    spec: QuerySpec
    bindings: tuple[Binding, ...]

    def __post_init__(self) -> None:
        owned = [binding.field for binding in self.bindings]
        if sorted(owned) != sorted(SpecField):
            raise ValueError(
                "every spec field has exactly one binder; these have none or two: "
                f"{sorted(field.value for field in set(SpecField).symmetric_difference(owned))}"
                f" (fields bound: {[field.value for field in owned]})"
            )
        for binding in self.bindings:
            state = self.state_of(binding.field)
            if isinstance(state, Unbound) is not (binding.precedence is Precedence.UNBOUND):
                raise ValueError(
                    f"{binding.field.value} is recorded as {binding.precedence.value} and "
                    f"the spec carries {type(state).__name__}; the record and the spec are "
                    "one statement, not two"
                )

    @property
    def by_field(self) -> dict[SpecField, Binding]:
        return {binding.field: binding for binding in self.bindings}

    def state_of(self, field: SpecField) -> FieldState[object]:
        """The spec's state for *field* -- read by name so the record cannot drift."""
        state: FieldState[object] = getattr(self.spec, field.value)
        return state

    @property
    def is_answerable(self) -> bool:
        """Is every field either resolved or determinately deferred?

        ``Deferred`` counts: the reader was perfectly clear and ``execute/`` resolves it.
        Only ``Unbound`` makes the answer a clarification or a refusal (AD-1).
        """
        return all(
            isinstance(self.state_of(field), Bound | Deferred) for field in SpecField
        )


def bindable_fields() -> tuple[str, ...]:
    """The ``QuerySpec`` fields a binder is responsible for, read off the spec itself."""
    unbindable = frozenset({"today", "spec_version"})
    return tuple(item.name for item in fields(QuerySpec) if item.name not in unbindable)
