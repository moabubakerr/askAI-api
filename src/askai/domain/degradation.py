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

``kind`` names a member of the **closed taxonomy** ``DegradationKind``, which Story 1.17
drew and which lives in ``askai.observability.degradations``. The field's annotation is
``str`` rather than the enum for one structural reason: this module imports nothing
in-project (AD-2, enforced by the ``domain imports nothing in-project`` import-linter
contract), so the enum cannot be named here, and ``domain/`` is the only package the
enum could otherwise have lived in. Closure is therefore enforced at the two places that
decide anything: ``classify`` rejects a non-member, so an unrecognised kind can be
neither counted (``Tally.of``) nor carried on a result (``Carried``, ``Failed``); and
``tests/test_degradations.py`` scans every ``Degradation(...)`` construction under
``src/askai/`` and fails on a kind the enum does not declare. Producers should build
through ``degrade(DegradationKind.X, where, detail)`` rather than calling this
constructor with a bare string, so the compiler catches an invented kind first.
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
    """A ``DegradationKind`` value -- the closed taxonomy, counted per kind.

    Typed as ``str`` only because ``domain/`` may not import the package the enum lives
    in; see the module docstring for how the set is closed regardless.
    """

    where: str
    """The layer or component it happened in -- so a rising rate has an address."""

    detail: str
    """What specifically, in enough detail to reconstruct the decision later."""
