"""Rows -> Answer.

Purity: pure.

Two guarantees live in this package and nowhere else:

* **One formatter** (AD-18). ``Formatter`` is the only route from a published value to a
  string, it takes the detail's published unit and Format field plus an explicit
  ``FormatMode``, and it reads every constant it applies out of ``rules/`` and every
  digit and separator out of ``messages/``.
* **Provenance is structural** (AD-6, AD-7). An element is built from a ``Provenance``,
  so it cannot exist without one, and an element whose ``source_ref`` does not resolve is
  refused with a typed ``Degradation`` rather than dropped.
* **The answer states what it did** (FR-56, AD-23). Every answer carries an element of
  role ``scope`` naming the grain, the period and the country scope it used, composed
  from the bilingual catalogue rather than dumped from the spec -- and the role tables
  in ``rules/`` decide which lens shows it and at which precision its figures are
  written, so no composer names a lens or a ``FormatMode``.
"""

from __future__ import annotations

from askai.assemble.elements import absent, build, derived, measured
from askai.assemble.format import (
    DisplayClause,
    DisplayRule,
    FormatMode,
    FormattedValue,
    Formatter,
    PublishedFormat,
    published_decimals,
)
from askai.assemble.provenance import (
    Admitted,
    Assembled,
    Provenance,
    ProvenanceFailure,
    Refused,
    admit,
    admit_all,
)
from askai.assemble.roles import (
    Lens,
    Placed,
    Placement,
    PlacementClause,
    PlacementError,
    PlacementRule,
    Role,
)
from askai.assemble.scope import ScopeMessage, scope_element, scope_statement

__all__ = [
    "Admitted",
    "Assembled",
    "DisplayClause",
    "DisplayRule",
    "FormatMode",
    "FormattedValue",
    "Formatter",
    "Lens",
    "Placed",
    "Placement",
    "PlacementClause",
    "PlacementError",
    "PlacementRule",
    "Provenance",
    "ProvenanceFailure",
    "PublishedFormat",
    "Refused",
    "Role",
    "ScopeMessage",
    "absent",
    "admit",
    "admit_all",
    "build",
    "derived",
    "measured",
    "published_decimals",
    "scope_element",
    "scope_statement",
]
