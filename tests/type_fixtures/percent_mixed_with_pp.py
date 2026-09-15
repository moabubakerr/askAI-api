"""NEGATIVE fixture: ``Percent`` arithmetic with ``pp``.

This file is **expected to fail** ``mypy --strict``. It is excluded from the main
type-check run by ``[tool.mypy] exclude`` and is checked on its own, as a subprocess,
by ``tests/test_type_invariants.py``.

AD-4 / FR-21: ``Percent`` and ``pp`` are distinct types and no implicit conversion
exists in either direction. Both directions are exercised, because a conversion added
on one side only would leave this passing in the other.
"""

from __future__ import annotations

from decimal import Decimal

from askai.domain.numbers import Percent, pp

# error: Argument 1 to "__add__" of "Percent" has incompatible type "PercentagePoints"
PERCENT_PLUS_PP = Percent(Decimal("2.6")) + pp(Decimal("0.4"))

# error: Argument 1 to "__add__" of "PercentagePoints" has incompatible type "Percent"
PP_PLUS_PERCENT = pp(Decimal("0.4")) + Percent(Decimal("2.6"))
