"""Rule data + loaders: *.yaml, loaders and startup validation.

Purity: pure after load.

The rules the engine answers by are data files under ``data/``, one schema in
``schema.py``, a loader in ``loader.py`` that refuses to return anything when a file is
missing or wrong, and the enumerate command in ``cli.py`` (AD-11, FR-70).

Reach a reader-affecting constant through ``rules().value(...)``. A literal in
``compile/``, ``execute/`` or ``assemble/`` is the defect this package exists to end,
and ``tests/test_rules.py`` scans for one.
"""

from __future__ import annotations

from askai.rules.loader import (
    DATA_DIR,
    LoadedRule,
    RuleLoadError,
    RuleRejectedError,
    RuleSet,
    load_rules,
    rules,
)
from askai.rules.schema import PER_CENT, Rule, RuleFile, RuleKind, RuleStatus, RuleValue

__all__ = [
    "DATA_DIR",
    "PER_CENT",
    "LoadedRule",
    "Rule",
    "RuleFile",
    "RuleKind",
    "RuleLoadError",
    "RuleRejectedError",
    "RuleSet",
    "RuleStatus",
    "RuleValue",
    "load_rules",
    "rules",
]
