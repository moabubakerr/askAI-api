"""Structural invariants over the whole tree, not over any one type.

These are the assertions that cannot be made by a type: properties of every module
under ``src/askai/`` at once. Each is written so it keeps biting as the tree grows --
a scan, never a list of the modules that happen to exist today.

Where a property's *behaviour* arrives in a later story, the structural half is
asserted now and the behavioural half is added there (epic context, 1.18).
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
from collections.abc import Iterator
from pathlib import Path

import pytest

import askai
from askai.domain import text as text_module

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"
DOMAIN_ROOT = PACKAGE_ROOT / "domain"

# Exclusions, not inclusions. A package listed in an inclusion list stops being scanned
# the moment someone adds a new one and forgets; an exclusion list has to be edited
# deliberately, and the edit is the thing a reviewer sees.
#
# `domain/` is exempt from the period+grain scan because `LastN(n, grain)` legitimately
# carries a grain: it is an unresolved *request*, not a resolved `Period` that already
# owns one (see the spec's Design Notes).
PERIOD_GRAIN_EXEMPT = frozenset({"domain"})

# The home-country scan runs over every module under `src/askai/`. AD-5's actual failure
# mode -- looking the country up by name and so retrieving every benchmark but it -- will
# live in `compile/` and `adapters/`, not in `domain/`, so scanning `domain/` alone would
# watch the one place the defect cannot occur.
#
# One exemption, by path rather than by package, and it is a real one: the root package
# docstring says what the product is for, in prose, and holds no code at all. Naming the
# country in a sentence about the product is not the defect; constructing a filter from
# the literal is. Anything added to this set needs the same argument made explicitly.
HOME_COUNTRY_EXEMPT_PATHS = frozenset({"__init__.py"})

HOME_COUNTRY_LITERAL = "qatar"


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _package_files(exempt: frozenset[str]) -> list[Path]:
    """Every module under ``src/askai/`` whose top-level package is not exempt."""
    return [
        path
        for path in _python_files(PACKAGE_ROOT)
        if path.relative_to(PACKAGE_ROOT).parts[0] not in exempt
    ]


def _home_country_scan_files() -> list[Path]:
    """Every module under ``src/askai/`` except the explicitly exempted paths."""
    return [
        path
        for path in _python_files(PACKAGE_ROOT)
        if path.relative_to(PACKAGE_ROOT).as_posix() not in HOME_COUNTRY_EXEMPT_PATHS
    ]


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _parsed(root: Path) -> Iterator[tuple[Path, ast.Module]]:
    for path in _python_files(root):
        yield path, _parse(path)


def _imported_modules() -> list[str]:
    """Every module under ``askai``, imported. A scan of files would miss nothing here,
    but importing is what proves the package actually loads with no in-project import."""

    def _fail(name: str) -> None:
        # walk_packages swallows import errors by default, so a module that fails to
        # import would simply never be checked -- the scan would go green by skipping
        # exactly the module something is wrong with.
        raise AssertionError(f"{name} could not be imported, so it was never checked")

    names = [askai.__name__]
    for info in pkgutil.walk_packages(askai.__path__, prefix=f"{askai.__name__}.", onerror=_fail):
        names.append(info.name)
    return names


# --------------------------------------------------- no period + grain in one signature


def _mentions(annotation: ast.expr | None, needle: str) -> bool:
    if annotation is None:
        return False
    return needle.lower() in ast.unparse(annotation).lower()


def _takes_both_a_period_and_a_grain(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = node.args
    every = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    if args.vararg:
        every.append(args.vararg)
    if args.kwarg:
        every.append(args.kwarg)

    has_period = any(
        "period" in arg.arg.lower() or _mentions(arg.annotation, "Period") for arg in every
    )
    has_grain = any(
        "grain" in arg.arg.lower() or _mentions(arg.annotation, "Grain") for arg in every
    )
    return has_period and has_grain


def test_no_public_callable_takes_both_a_period_and_a_grain() -> None:
    """The ERD note, made enforceable.

    A datapoint is unique on ``(detail, period, country)`` and the period string carries
    the grain, so a signature taking both admits a combination the data cannot
    represent. ``LastN(n, grain)`` is deliberately *not* caught by this: it lives in
    ``domain/`` and is an unresolved request, not a resolved ``Period`` (see the spec's
    Design Notes).
    """
    offenders: list[str] = []
    for path in _package_files(PERIOD_GRAIN_EXEMPT):
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name.startswith("_"):
                continue
            if _takes_both_a_period_and_a_grain(node):
                relative = path.relative_to(PROJECT_ROOT).as_posix()
                offenders.append(f"{relative}:{node.lineno} {node.name}")

    assert not offenders, "signature takes both a period and a grain: " + ", ".join(offenders)


def test_the_period_and_grain_scan_would_catch_an_offender() -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""
    tree = ast.parse(
        "def fetch(detail: str, period: Period, grain: Grain) -> None: ...\n"
        "def innocent(detail: str, period: Period) -> None: ...\n"
    )
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert [_takes_both_a_period_and_a_grain(node) for node in functions] == [True, False]


def test_the_scan_catches_a_grain_carried_only_in_an_annotation() -> None:
    """Renaming the argument must not be a way past the gate."""
    tree = ast.parse("def fetch(period: Period, at: Grain) -> None: ...\n")
    node = tree.body[0]
    assert isinstance(node, ast.FunctionDef)
    assert _takes_both_a_period_and_a_grain(node)


# --------------------------------------------------- one is_published_text


def test_is_published_text_is_defined_exactly_once() -> None:
    definitions: list[str] = []
    for path, tree in _parsed(PACKAGE_ROOT):
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == "is_published_text"
            ):
                relative = path.relative_to(PROJECT_ROOT).as_posix()
                definitions.append(f"{relative}:{node.lineno}")
    assert definitions == ["src/askai/domain/text.py:" + str(_definition_line())], (
        "there must be exactly one is_published_text; found " + ", ".join(definitions)
    )


def _definition_line() -> int:
    tree = ast.parse((DOMAIN_ROOT / "text.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "is_published_text":
            return node.lineno
    raise AssertionError("is_published_text is not defined in askai/domain/text.py")


def test_every_call_site_resolves_to_the_same_function_object() -> None:
    """Not "there is one definition" but "everyone reaches the same object".

    A re-export is fine; a re-implementation, a wrapper or a partial is not, because
    the whole point of a single predicate is that a gap is a gap everywhere.
    """
    for name in _imported_modules():
        module = importlib.import_module(name)
        found = getattr(module, "is_published_text", None)
        if found is None:
            continue
        assert found is text_module.is_published_text, (
            f"{name}.is_published_text is not askai.domain.text.is_published_text"
        )


# --------------------------------------------------- no ambient degradation collector


def test_nothing_under_src_imports_contextvars() -> None:
    """AD-15: degradations travel on the result value.

    A contextvar would reintroduce exactly the shared mutable state AD-2 exists to
    prevent, and would make assemble/ untestable in isolation.
    """
    offenders: list[str] = []
    for path, tree in _parsed(PACKAGE_ROOT):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import | ast.ImportFrom):
                continue
            for name in _imported_names(node, _package_of(path)):
                if name.split(".")[0] == "contextvars":
                    relative = path.relative_to(PROJECT_ROOT).as_posix()
                    offenders.append(f"{relative}:{node.lineno}")
    assert not offenders, "contextvars imported: " + ", ".join(offenders)


def _package_of(path: Path) -> str:
    """The dotted package a module lives in -- what a relative import resolves against."""
    parts = list(path.relative_to(PACKAGE_ROOT).parts)[:-1]
    return ".".join(["askai", *parts])


def _imported_names(node: ast.Import | ast.ImportFrom, package: str) -> list[str]:
    """The absolute module names an import statement refers to.

    A relative import carries its depth in ``node.level`` and only the tail in
    ``node.module``, so reading ``node.module`` alone reports ``from ..execute import x``
    as ``execute`` -- a name that does not start with ``askai.`` and sails past a check
    looking for one. Since that check is the backstop if an import-linter contract is
    ever mis-scoped, the level is resolved against *package* here.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not node.level:
        return [node.module] if node.module else []
    # level 1 is the containing package, level 2 its parent, and so on.
    parts = package.split(".")
    base = ".".join(parts[: len(parts) - (node.level - 1)])
    if node.module:
        return [f"{base}.{node.module}"]
    return [f"{base}.{alias.name}" for alias in node.names]


# The shapes an ambient collector actually takes. Bare-name calls (`list()`, `deque()`)
# and attribute calls (`collections.defaultdict(list)`) alike -- the second form is an
# `ast.Attribute`, so matching only `ast.Name` would miss the most idiomatic spelling.
_MUTABLE_FACTORIES = frozenset({"list", "dict", "set", "defaultdict", "Counter", "deque"})


def _assigned_names(node: ast.Assign | ast.AnnAssign) -> list[str]:
    """Every name a module-level assignment binds, including inside a tuple target.

    Returning ``[]`` for a shape it does not understand would be worse than useless:
    the caller's ``all(startswith("__"))`` guard is vacuously true on an empty list, so
    an unrecognised target would skip the node entirely. Attribute and subscript
    targets are reported under a sentinel so they are never mistaken for dunders.
    """
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names: list[str] = []
    for target in targets:
        for element in ast.walk(target):
            if isinstance(element, ast.Name):
                names.append(element.id)
            elif isinstance(element, ast.Attribute | ast.Subscript):
                names.append("<not-a-name>")
    return names


def _is_module_level_mutable(node: ast.Assign | ast.AnnAssign) -> bool:
    value = node.value
    if value is None:
        return False
    names = _assigned_names(node)
    # `__all__` is a list by language convention and is read, never appended to. An
    # empty name list is *not* treated as all-dunder; see _assigned_names.
    if names and all(name.startswith("__") for name in names):
        return False
    return _is_mutable_value(value)


def _is_mutable_value(value: ast.expr) -> bool:
    if isinstance(value, ast.List | ast.Dict | ast.Set):
        return True
    # `A, B = [], {}` puts the collections inside a Tuple, so the assignment's value is
    # not itself a collection and a shallow check waves it through.
    if isinstance(value, ast.Tuple):
        return any(_is_mutable_value(element) for element in value.elts)
    if isinstance(value, ast.Call):
        func = value.func
        if isinstance(func, ast.Name):
            return func.id in _MUTABLE_FACTORIES
        if isinstance(func, ast.Attribute):
            return func.attr in _MUTABLE_FACTORIES
    return False


def test_no_module_level_mutable_collector_exists() -> None:
    """A module-level list, dict or set is the shape an ambient collector takes."""
    offenders: list[str] = []
    for path, tree in _parsed(PACKAGE_ROOT):
        for node in tree.body:
            if isinstance(node, ast.Assign | ast.AnnAssign) and _is_module_level_mutable(node):
                offenders.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}")
    assert not offenders, "module-level mutable state: " + ", ".join(offenders)


@pytest.mark.parametrize(
    ("source", "caught"),
    [
        ("DEGRADATIONS = []", True),
        ("DEGRADATIONS: list[str] = []", True),
        ("SEEN = {}", True),
        ("SEEN = set()", True),
        ("COLLECTED = list()", True),
        ("BY_KIND = collections.defaultdict(list)", True),  # ast.Attribute call
        ("PENDING = collections.deque()", True),  # ast.Attribute call
        ("COUNTS = collections.Counter()", True),
        ("A, B = [], {}", True),  # tuple target
        ("_registry.items = []", True),  # attribute target
        ("__all__ = ['x']", False),
        ("KINDS = frozenset({'a'})", False),
        ("NAME = 'x'", False),
        ("PAIRS = ('a', 'b')", False),
    ],
)
def test_the_collector_scan_matches_the_shapes_that_matter(source: str, caught: bool) -> None:
    """Drives the scan's own predicate -- not a re-implementation of it.

    A meta-test that checks the shape inline proves the test author's understanding and
    nothing about the matcher the real scan runs.
    """
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.Assign | ast.AnnAssign)
    assert _is_module_level_mutable(node) is caught


# --------------------------------------------------- Qatar is not a country value


@pytest.mark.parametrize(
    "path",
    _home_country_scan_files(),
    ids=lambda p: p.relative_to(PACKAGE_ROOT).as_posix(),
)
def test_the_home_country_is_never_named_as_a_literal(path: Path) -> None:
    """AD-5 / FR-11b, over the whole package rather than over ``domain/``.

    National scope is the *absence* of a country: the benchmark config names the home
    country in all 21 declared sets while the data names it in none of 8,127 rows, so a
    filter built by name retrieves every benchmark and silently drops it. The literal is
    banned outright rather than reviewed for -- and banned everywhere, because the
    construction that does the damage belongs to ``compile/`` and ``adapters/``, not to
    ``domain/``, which is the one place it could not happen.
    """
    source = path.read_text(encoding="utf-8").lower()
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    assert HOME_COUNTRY_LITERAL not in source, f"{relative} names the home country"


def test_the_home_country_scan_covers_the_whole_package_bar_the_stated_exemption() -> None:
    """Guard against the parametrisation silently collapsing to a handful of files, and
    against the exemption list quietly growing."""
    scanned = set(_home_country_scan_files())
    missing = set(_python_files(PACKAGE_ROOT)) - scanned
    assert {path.relative_to(PACKAGE_ROOT).as_posix() for path in missing} == {"__init__.py"}
    assert len(scanned) >= 25, "the scan must reach every package, not just domain/"


# --------------------------------------------------- domain purity, from the inside


def _in_project_imports_outside_domain(tree: ast.Module, package: str) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for name in _imported_names(node, package):
            if name.startswith("askai.") and not name.startswith("askai.domain"):
                found.append(f"{node.lineno} -> {name}")
    return found


def test_no_domain_module_imports_anything_in_project_but_domain() -> None:
    """``lint-imports`` owns this contract; this is the same claim at module level,
    so a mis-scoped contract cannot leave it unasserted."""
    offenders: list[str] = []
    for path, tree in _parsed(DOMAIN_ROOT):
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        offenders.extend(
            f"{relative}:{found}"
            for found in _in_project_imports_outside_domain(tree, _package_of(path))
        )
    assert not offenders, "domain reached outside itself: " + ", ".join(offenders)


@pytest.mark.parametrize(
    ("source", "caught"),
    [
        ("from askai.execute import fetch", True),
        ("import askai.adapters.store", True),
        ("from ..execute import fetch", True),  # relative: `node.module` alone says "execute"
        ("from .. import execute", True),
        ("from askai.domain.period import Period", False),
        ("from .period import Period", False),  # a sibling inside domain/ is fine
        ("from . import period", False),
        ("import re", False),
    ],
)
def test_the_domain_purity_scan_catches_a_relative_import(source: str, caught: bool) -> None:
    """The backstop for `lint-imports` must not be evadable by an import style.

    `from ..execute import x` reports `node.module == "execute"`, which does not start
    with `askai.` -- so before the level was resolved this scan waved it straight
    through, and it is the only check standing if a contract is ever mis-scoped.
    Evaluated as though the file were a module inside `askai.domain`.
    """
    found = _in_project_imports_outside_domain(ast.parse(source), "askai.domain")
    assert bool(found) is caught
