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

__all__ = [
    "Admitted",
    "Assembled",
    "DisplayClause",
    "DisplayRule",
    "FormatMode",
    "FormattedValue",
    "Formatter",
    "Provenance",
    "ProvenanceFailure",
    "PublishedFormat",
    "Refused",
    "absent",
    "admit",
    "admit_all",
    "build",
    "derived",
    "measured",
    "published_decimals",
]
