"""NEGATIVE fixture: an ``Element`` built without a ``source_ref``.

This file is **expected to fail** ``mypy --strict``. It is excluded from the main
type-check run by ``[tool.mypy] exclude`` and is checked on its own, as a subprocess,
by ``tests/test_type_invariants.py``.

AD-6: there is no constructor that produces an element without a ``source_ref``. This
is the assertion that no overload, default or classmethod has quietly added one.
"""

from __future__ import annotations

from askai.domain.element import Element, ElementClass

# error: Missing positional argument "source_ref" in call to "Element"
WITHOUT_SOURCE = Element("inflation was 2.6%", ElementClass.MEASURED)
