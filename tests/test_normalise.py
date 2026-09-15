"""The one normalisation: what it folds, and that it stays the only one.

Two halves, and the second is the one that keeps biting. The first says what
``normalise()`` does to text -- rule by rule, and then as whole sets of surface
forms that must land on one string. The second says there is still exactly one
of it: a scan of every module under ``src/askai/`` for a second implementation,
and a check that every module reaching for the name reaches this same function
object (AD-26, story 1.3).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import types
import unicodedata
from pathlib import Path

import pytest

import askai
from askai.domain import normalise as normalise_module
from askai.domain.normalise import normalise

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"
THE_ONE_MODULE = PACKAGE_ROOT / "domain" / "normalise.py"

# The spellings a second implementation would arrive under. The tree being replaced
# used three of them for the same fold -- `candidates.normalise`, `retrieval.normalise`
# and `groups.norm` -- so `norm` is on this list from experience, not from caution.
NORMALISER_NAMES = frozenset(
    {
        "norm",
        "normalise",
        "normalize",
        "normalise_text",
        "normalize_text",
        "_normalise",
        "_normalize",
        "fold_text",
        "normal_form",
    }
)


def _python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _definitions_named(names: frozenset[str]) -> list[str]:
    """Every function or method under ``src/askai/`` whose name is in *names*."""
    found: list[str] = []
    for path in _python_files(PACKAGE_ROOT):
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in names:
                found.append(f"{path.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}")
    return found


def _the_one_definition() -> str:
    for node in ast.walk(_parse(THE_ONE_MODULE)):
        if isinstance(node, ast.FunctionDef) and node.name == "normalise":
            return f"{THE_ONE_MODULE.relative_to(PROJECT_ROOT).as_posix()}:{node.lineno}"
    raise AssertionError("normalise is not defined in askai/domain/normalise.py")


def _imported_modules() -> list[str]:
    """Every module under ``askai``, imported.

    Imported rather than scanned: the claim being tested is about objects at
    runtime, and a re-export is invisible to a file scan.
    """

    def _fail(name: str) -> None:
        # walk_packages swallows import errors, so a module that fails to import
        # would simply never be checked and the scan would go green by skipping it.
        raise AssertionError(f"{name} could not be imported, so it was never checked")

    names = [askai.__name__]
    for info in pkgutil.walk_packages(askai.__path__, prefix=f"{askai.__name__}.", onerror=_fail):
        names.append(info.name)
    return names


# --------------------------------------------------- there is exactly one of it


def test_no_second_normalisation_exists_anywhere_under_askai() -> None:
    """AD-26's build gate: a second implementation fails, wherever it is written.

    Named spellings rather than a similarity heuristic, because the failure this
    prevents is a copy -- someone writing the fold again under a nearby name, which
    is exactly what the three copies in the tree being replaced were.
    """
    found = _definitions_named(NORMALISER_NAMES)
    assert found == [_the_one_definition()], (
        "there must be exactly one normalisation; found " + ", ".join(found)
    )


def test_the_second_implementation_scan_would_catch_an_offender() -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""
    tree = ast.parse("def norm(s: str) -> str: ...\ndef unrelated(s: str) -> str: ...\n")
    caught = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in NORMALISER_NAMES
    ]
    assert caught == ["norm"]


def test_every_call_site_resolves_to_the_same_function_object() -> None:
    """Not "there is one definition" but "everyone reaches the same object".

    A re-export is fine; a re-implementation, a wrapper or a partial is not, because
    the whole point of one normalisation is that an index and a query fold alike.
    """
    for name in _imported_modules():
        module = importlib.import_module(name)
        found = getattr(module, "normalise", None)
        if found is None:
            continue
        # Importing `askai.domain.normalise` binds the *module* on its parent package
        # under the same name; that attribute is not a call site.
        if isinstance(found, types.ModuleType):
            assert found is normalise_module, f"{name}.normalise is a different module"
            continue
        assert found is normalise, f"{name}.normalise is not askai.domain.normalise.normalise"


def test_the_module_exports_only_normalise() -> None:
    assert normalise_module.__all__ == ["normalise"]


def test_normalise_takes_no_configuration() -> None:
    """"No configuration and no variants" is a signature property before it is a habit.

    A second parameter -- a flag, a mode, a locale -- is a second normalisation that
    the single-definition scan above cannot see.
    """
    parameters = list(inspect.signature(normalise).parameters.values())
    assert len(parameters) == 1, f"normalise takes configuration: {parameters}"
    assert parameters[0].default is inspect.Parameter.empty


# --------------------------------------------------- rule by rule


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # NFKC: full-width Latin, a compatibility ligature, and an Arabic
        # presentation form are the same text as the ordinary spelling.
        ("ＧＤＰ", "gdp"),
        ("ﬁnance", "finance"),
        ("ﻟﺎ", "لا"),  # LAM + ALEF, isolated presentation forms
        # Case folding.
        ("GDP", "gdp"),
        ("İstanbul".casefold(), normalise("İstanbul")),
        # Diacritics: Arabic harakat, then Latin accents.
        ("مُعَدَّل", "معدل"),
        ("الْتَّضَخُّم", "التضخم"),
        ("Café", "cafe"),
        # Tatweel.
        ("معــــدل", "معدل"),
        # Letter forms.
        ("أإآ", "ااا"),
        ("مستوى", "مستوي"),
        ("نسبة", "نسبه"),
        # Punctuation and whitespace collapse to one space, ends stripped.
        ("  gdp   per\tcapita\n", "gdp per capita"),
        ("gdp-per-capita", "gdp per capita"),
        ("gdp_per_capita", "gdp per capita"),
        ("g.d.p., 2024!", "g d p 2024"),
        ("الناتج، المحلي؛ الإجمالي؟", "الناتج المحلي الاجمالي"),
        ("%", ""),
        ("", ""),
        ("   ", ""),
    ],
)
def test_the_fold_rule_by_rule(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_hamza_on_waw_and_yeh_is_not_folded() -> None:
    """The stated list is three alef forms, and stopping there is the decision.

    Decomposing the whole string to strip diacritics would also split the hamza off
    waw and yeh, folding two letters AD-26 does not name and the measured
    predecessors kept apart. This test is what makes that a choice rather than an
    accident of implementation order.
    """
    assert normalise("مسؤول") == "مسؤول"
    assert normalise("مسئول") == "مسئول"
    assert normalise("مسؤول") != normalise("مسئول")


def test_digits_are_not_folded_across_scripts() -> None:
    """Arabic-Indic digits are not in AD-26's list, and NFKC does not fold them.

    Asserted so that a later story adding digit folding does it deliberately, here,
    rather than discovering it by a failing corpus entry.
    """
    assert normalise("٢٠٢٤") == "٢٠٢٤"


# --------------------------------------------------- whole surface-form sets


# Each set is one word written the several ways a reader actually types it --
# differing only by diacritics, tatweel, hamza form, or final yeh / teh marbuta.
# Every member of a set must produce one string; which string is not the point.
SURFACE_FORM_SETS = [
    pytest.param(["المالية", "الماليه", "المَالِيَّة", "الماليــة", "المالية."], id="maliyya"),
    pytest.param(["إجمالي", "اجمالي", "أجمالي", "آجمالي", "إجمَالي"], id="ijmali"),
    pytest.param(["مستوى", "مستوي", "مُستوى", "مستـوى"], id="mustawa"),
    pytest.param(["نسبة البطالة", "نسبه البطاله", "نِسبة البَطالة", "نسبة  البطالة"], id="bitala"),
    pytest.param(["معدل التضخم", "مُعَدَّل التضخم", "معدل، التضخم", "معدل التضخـم"], id="tadakhkhum"),
    # "G.D.P" is deliberately absent: it folds to three tokens, and it should. The
    # separator collapses to a space, so a word is never fused with its neighbour.
    pytest.param(
        ["GDP per capita", "gdp-per-capita", "GDP, per capita!", "  gdp per  capita  "],
        id="gdp-per-capita",
    ),
]


@pytest.mark.parametrize("forms", SURFACE_FORM_SETS)
def test_every_surface_form_in_a_set_folds_to_one_string(forms: list[str]) -> None:
    folded = {normalise(form) for form in forms}
    assert len(folded) == 1, f"{forms} folded to {sorted(folded)}"


@pytest.mark.parametrize("forms", SURFACE_FORM_SETS)
def test_the_sets_are_not_trivially_equal_before_folding(forms: list[str]) -> None:
    """Guards the test above from passing because the fixtures are the same string."""
    assert len(set(forms)) == len(forms)


# --------------------------------------------------- properties of the fold itself


@pytest.mark.parametrize(
    "raw",
    ["", "gdp", "معدل التضخم", "المَالِيَّة", "Café — GDP, 2024", "ＧＤＰ  per_capita"],
)
def test_normalising_a_normal_form_changes_nothing(raw: str) -> None:
    """Idempotence. An index built from stored normal forms is re-normalised by
    every lookup; if the second pass moved, the index and the query would diverge
    on exactly the inputs that had already been folded once."""
    once = normalise(raw)
    assert normalise(once) == once


@pytest.mark.parametrize("raw", ["gdp", "معدل التضخم", "Café — GDP, 2024"])
def test_the_result_carries_no_marks_punctuation_or_repeated_space(raw: str) -> None:
    result = normalise(raw)
    assert all(unicodedata.category(character) != "Mn" for character in result)
    assert all(not unicodedata.category(character).startswith("P") for character in result)
    assert "  " not in result
    assert result == result.strip()


def test_the_fold_is_pure_for_the_same_input() -> None:
    """No clock, no configuration, no state: the same input twice is the same output."""
    raw = "مُعَدَّل التضخم, 2024"
    assert normalise(raw) == normalise(raw)
    assert raw == "مُعَدَّل التضخم, 2024"  # and the argument is untouched
