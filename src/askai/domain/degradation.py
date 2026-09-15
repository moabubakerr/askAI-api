"""``Degradation`` -- a soft failure, typed, and carried on the result value.

Purity: pure, imports nothing in-project.

AD-15: fail-soft remains policy; silence does not. A rule that stopped firing must
never be indistinguishable from one that was never reached, which is what the
predecessor's ``except Exception`` density made it.

**Degradations travel on the result value -- never through an ambient collector or a
contextvar.** That is not a style preference. A module-level collector is the shared
mutable state AD-2 exists to prevent: it would make ``assemble/`` untestable in
isolation, make two concurrent requests able to read each other's failures, and put
the record's contents out of reach of the function that produced them. So this module
defines a value and nothing else -- no registry, no counter, no ``report()``.
``tests/test_domain_invariants.py`` asserts no ``contextvars`` import and no
module-level mutable collector exists anywhere under ``src/askai/``.

``kind`` is a plain string for now. The closed taxonomy belongs to Story 1.17, which
counts them and carries them into the answer record; inventing one here would be a
guess at a set this story has no acceptance criterion for.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Degradation"]


@dataclass(frozen=True, slots=True)
class Degradation:
    """One thing that went less than fully right, named well enough to act on.

    Frozen, like everything a result carries: a degradation recorded in ``execute/``
    and read in ``observability/`` is the same value, not a mutable one that acquired
    detail on the way.
    """

    kind: str
    """What went wrong. Story 1.17 closes this into an enum and counts it."""

    where: str
    """The layer or component it happened in -- so a rising rate has an address."""

    detail: str
    """What specifically, in enough detail to reconstruct the decision later."""
