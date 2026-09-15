"""Story 1.13 -- the provenance envelope, and the one formatter.

Two properties, and each is asserted twice: once behaviourally, on the code as it runs,
and once structurally, as a scan that keeps biting as the tree fills.

1. **One formatter owns value-to-string** (AD-18, FR-47, FR-48). ``Headline`` applies the
   display rounding rule and ``Evidence`` preserves the published precision; the mode and
   the language are explicit on every call; every constant comes from ``rules/`` and every
   digit and separator from ``messages/``; and no composer builds a numeric string by any
   other route.
2. **Provenance is structural** (AD-6, AD-7, FR-44, FR-45). An element is built from a
   ``Provenance`` carrying detail, grain, period, country and publishing source; its class
   is set at construction and is immutable; ``absent`` is a class carrying content; and an
   element whose ``source_ref`` does not resolve is refused as a typed ``Degradation``
   rather than dropped.

FR-55's *"no figure is produced, formatted or restated by a language model"* is trivially
true in this epic because nothing calls a model. The scan at the end asserts the trivial
version now so that the first import of a model client on the answer path fails the build
rather than passing review.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from askai.assemble import (
    Admitted,
    Assembled,
    FormatMode,
    Formatter,
    Provenance,
    ProvenanceFailure,
    PublishedFormat,
    Refused,
    absent,
    admit,
    admit_all,
    build,
    measured,
    published_decimals,
)
from askai.domain.degradation import Degradation
from askai.domain.element import Element, ElementClass
from askai.domain.numbers import Percent, PercentagePoints
from askai.domain.period import Grain, Period
from askai.messages import Catalogue, Lang, load_catalogue
from askai.rules import rules

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "askai"
ASSEMBLE_ROOT = PACKAGE_ROOT / "assemble"

# The one module allowed to reach the number-writing machinery. Everything else in the
# composing layers goes through `Formatter`.
THE_FORMATTER = ASSEMBLE_ROOT / "format.py"

# The layers that compose an answer out of figures. `execute/` is excluded deliberately:
# it produces values, never strings, and is another story's territory.
COMPOSING_PACKAGES = ("assemble", "narrate", "respond")

# The shapes a second value-to-string route takes: the builtins that turn a number into
# text, and the `Decimal` method that applies a precision.
NUMBER_TO_STRING_CALLS = frozenset({"round", "format", "format_number", "format_value"})
NUMBER_TO_STRING_METHODS = frozenset({"quantize"})
NUMBER_TO_STRING_IMPORTS = frozenset(
    {"askai.messages.numbers", "format_number", "format_value"}
)

# A model client, by any of the names one arrives under. FR-55/AD-3: no figure is
# produced, formatted or restated by a language model anywhere on the answer path.
MODEL_LIBRARIES = frozenset({"openai", "anthropic", "httpx", "langchain", "ollama", "requests"})


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load_catalogue()


@pytest.fixture(scope="module")
def formatter(catalogue: Catalogue) -> Formatter:
    return Formatter(catalogue=catalogue, rule_set=rules())


def a_period() -> Period:
    return Period("2026-04")


def a_provenance(country: str | None = None) -> Provenance:
    return Provenance(
        detail_id="D-CPI-HEADLINE",
        period=a_period(),
        country=country,
        source_id="S-PSA-CPI",
    )


class Resolving:
    """A source catalogue that holds exactly the references it was given."""

    def __init__(self, *known: str) -> None:
        self._known = frozenset(known)

    def resolves(self, source_ref: str) -> bool:
        return source_ref in self._known


# ------------------------------------------------------------------ the single formatter


def test_headline_applies_the_display_rounding_rule(formatter: Formatter) -> None:
    """FR-48: the published Format field says one decimal, so the headline shows one.

    686.131074 is the finding's own number: it reached a reader because it was formatted
    where it was found rather than by anything holding the rule.
    """
    written = formatter.format(
        Decimal("686.131074"), PublishedFormat(unit="%", spec="0.0"), FormatMode.HEADLINE, Lang.EN
    )
    assert written.value == "686.1"
    assert written.decimals == 1


def test_evidence_preserves_the_published_precision(formatter: Formatter) -> None:
    """The same value, in the evidence position, is shown exactly as published."""
    written = formatter.format(
        Decimal("686.131074"), PublishedFormat(unit="%", spec="0.0"), FormatMode.EVIDENCE, Lang.EN
    )
    assert written.value == "686.131074"
    assert written.decimals == 6


def test_one_value_renders_one_way_in_each_position(formatter: Formatter) -> None:
    """F-004, asserted: the mode is the only thing that may change the rendering."""
    published = PublishedFormat(unit="%", spec="0.00")
    value = Decimal("2.6499")
    headline = formatter.format(value, published, FormatMode.HEADLINE, Lang.EN)
    again = formatter.format(value, published, FormatMode.HEADLINE, Lang.EN)
    evidence = formatter.format(value, published, FormatMode.EVIDENCE, Lang.EN)
    assert headline == again
    assert headline.value == "2.65"
    assert evidence.value == "2.6499"


def test_a_format_field_that_says_nothing_falls_back_to_the_rule(formatter: Formatter) -> None:
    """``R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT``'s ``fallback_decimals``, read from data."""
    expected = rules().value("R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT", "fallback_decimals")
    written = formatter.format(
        Decimal("2.6499"), PublishedFormat(unit="%", spec=""), FormatMode.HEADLINE, Lang.EN
    )
    assert written.decimals == expected


def test_a_rank_is_an_integer_ordinal_whatever_the_format_field_says(
    formatter: Formatter,
) -> None:
    """``R-DISPLAY-RANK-IS-AN-INTEGER-ORDINAL``: "11.00th" is not a thing (finding 106)."""
    for spec in ("", "00", "0.00"):
        written = formatter.format(
            Decimal("11.004"), PublishedFormat(unit="Rank", spec=spec), FormatMode.HEADLINE, Lang.EN
        )
        assert written.value == "11"
        assert written.decimals == 0


def test_a_placeholder_unit_is_silent_rather_than_shown(formatter: Formatter) -> None:
    """``R-DISPLAY-PLACEHOLDER-UNIT-IS-SILENT``: the reader never sees the word."""
    silent = rules().value("R-DISPLAY-PLACEHOLDER-UNIT-IS-SILENT", "silent_units")
    assert isinstance(silent, tuple)
    for spelling in silent:
        written = formatter.format(
            Decimal("2.6"), PublishedFormat(unit=spelling, spec="0.0"), FormatMode.HEADLINE, Lang.EN
        )
        assert written.unit == ""


def test_a_placeholder_unit_is_matched_through_the_single_fold(formatter: Formatter) -> None:
    """A trailing space in an export must not be how the word reaches a reader."""
    written = formatter.format(
        Decimal("2.6"), PublishedFormat(unit=" na ", spec="0.0"), FormatMode.HEADLINE, Lang.EN
    )
    assert written.unit == ""


def test_a_real_unit_is_carried_through_as_published(formatter: Formatter) -> None:
    written = formatter.format(
        Decimal("2.6"), PublishedFormat(unit="QAR bn", spec="0.0"), FormatMode.HEADLINE, Lang.EN
    )
    assert written.unit == "QAR bn"


def test_the_digits_and_separators_come_from_the_catalogue(formatter: Formatter) -> None:
    """FR-62: how a figure is written is per-language data, not a branch in the formatter."""
    published = PublishedFormat(unit="%", spec="0.0")
    value = Decimal("12345.67")
    assert formatter.format(value, published, FormatMode.HEADLINE, Lang.EN).value == "12,345.7"
    assert formatter.format(value, published, FormatMode.HEADLINE, Lang.AR).value == "12٬345٫7"


def test_the_formatter_holds_no_constant_of_its_own() -> None:
    """Every number it applies is reachable by rule id and clause name.

    The AST half of this is ``tests/test_rules.py``'s scan of ``assemble/``; this is the
    positive half -- the rules the formatter names are actually there to be read.
    """
    rule_set = rules()
    assert rule_set.value("R-DISPLAY-RANK-IS-AN-INTEGER-ORDINAL", "decimals") == 0
    assert rule_set.value("R-DISPLAY-RANK-UNIT-SPELLINGS", "rank_units") == ("Rank",)
    assert isinstance(
        rule_set.value("R-DISPLAY-DECIMALS-FROM-PUBLISHED-FORMAT", "fallback_decimals"), int
    )


@pytest.mark.parametrize(
    ("spec", "decimals"),
    [
        ("", None),
        ("   ", None),
        ("Rank", None),
        ("00", 0),
        ("#,##0", 0),
        ("0.0", 1),
        ("bn0.00", 2),
        ("#,##0.000", 3),
    ],
)
def test_the_published_format_field_is_read_rather_than_guessed(
    spec: str, decimals: int | None
) -> None:
    assert published_decimals(spec) == decimals


def test_the_mode_and_the_language_have_no_default() -> None:
    """AD-18 and AD-11: both are decided by the caller's position, and neither defaults.

    A default mode is how a headline acquires evidence precision on one card; a default
    language is how an English sentence reaches an Arabic answer.
    """
    parameters = inspect.signature(Formatter.format).parameters
    assert parameters["mode"].default is inspect.Parameter.empty
    assert parameters["lang"].default is inspect.Parameter.empty


def test_a_float_never_reaches_the_formatter(formatter: Formatter) -> None:
    """AD-4: a published value that has been through binary floating point is not one."""
    with pytest.raises(TypeError):
        formatter.format(
            2.6,  # type: ignore[arg-type]
            PublishedFormat(unit="%", spec="0.0"),
            FormatMode.HEADLINE,
            Lang.EN,
        )


def test_a_non_finite_value_is_refused(formatter: Formatter) -> None:
    with pytest.raises(ValueError, match="finite"):
        formatter.format(
            Decimal("NaN"), PublishedFormat(unit="%", spec="0.0"), FormatMode.HEADLINE, Lang.EN
        )


def test_percent_and_percentage_points_both_format_and_neither_converts(
    formatter: Formatter,
) -> None:
    """FR-21/AD-4: the formatter renders each from its own value and never crosses them.

    The numerals match because the ``Decimal`` matches; what must never happen is the
    formatter turning one type into the other on the way, which the structural test below
    asserts by scanning for the construction that would do it.
    """
    published = PublishedFormat(unit="%", spec="0.0")
    percent = formatter.format(Percent(Decimal("2.64")), published, FormatMode.HEADLINE, Lang.EN)
    points = formatter.format(
        PercentagePoints(Decimal("2.64")), published, FormatMode.HEADLINE, Lang.EN
    )
    assert percent.value == points.value == "2.6"


def test_a_difference_of_two_percentages_formats_as_the_points_it_is(
    formatter: Formatter,
) -> None:
    movement = Percent(Decimal("3.2")) - Percent(Decimal("2.6"))
    assert isinstance(movement, PercentagePoints)
    written = formatter.format(
        movement, PublishedFormat(unit="pp", spec="0.0"), FormatMode.HEADLINE, Lang.EN
    )
    assert written.value == "0.6"
    assert written.unit == "pp"


# ------------------------------------------------ no composer formats by another route


def _modules(package: str) -> list[Path]:
    return sorted(path for path in (PACKAGE_ROOT / package).rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_names(node: ast.Import | ast.ImportFrom) -> Iterator[str]:
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name
    else:
        if node.module:
            yield node.module
        for alias in node.names:
            yield alias.name


def _second_formatting_routes(tree: ast.Module) -> list[tuple[str, int]]:
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            for name in _imported_names(node):
                if name in NUMBER_TO_STRING_IMPORTS:
                    found.append((f"imports {name}", node.lineno))
        elif isinstance(node, ast.Call):
            callee = node.func
            if isinstance(callee, ast.Name) and callee.id in NUMBER_TO_STRING_CALLS:
                found.append((f"calls {callee.id}()", node.lineno))
            elif isinstance(callee, ast.Attribute) and callee.attr in NUMBER_TO_STRING_METHODS:
                found.append((f"calls .{callee.attr}()", node.lineno))
    return found


@pytest.mark.parametrize("package", COMPOSING_PACKAGES)
def test_no_composer_builds_a_numeric_string_by_any_other_route(package: str) -> None:
    """AD-18's load-bearing sentence, asserted as a scan (FR-47).

    ``assemble/format.py`` is the single exemption and is exempt by path, so a second
    formatter added beside it is caught the moment it appears.
    """
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{line} {what}"
        for path in _modules(package)
        if path != THE_FORMATTER
        for what, line in _second_formatting_routes(_parse(path))
    ]
    assert not offences, (
        "a figure becomes a string through assemble.Formatter and nowhere else "
        "(AD-18):\n  " + "\n  ".join(offences)
    )


def test_the_second_route_scan_would_catch_one() -> None:
    """A scan that has never gone red is indistinguishable from one that cannot."""
    tree = ast.parse(
        "from askai.messages import format_value\n"
        "def show(v):\n"
        "    return format_value(c, l, round(v, 2))\n"
    )
    assert sorted(what for what, _ in _second_formatting_routes(tree)) == [
        "calls format_value()",
        "calls round()",
        "imports format_value",
    ]


def test_there_is_exactly_one_formatter_in_the_tree() -> None:
    """One class named ``Formatter`` under ``src/askai/``, and it is this one."""
    definitions = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno}"
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.ClassDef) and node.name == "Formatter"
    ]
    assert definitions == [f"assemble/format.py:{_formatter_line()}"]


def _formatter_line() -> int:
    for node in ast.walk(_parse(THE_FORMATTER)):
        if isinstance(node, ast.ClassDef) and node.name == "Formatter":
            return node.lineno
    raise AssertionError("assemble/format.py does not define Formatter")


def test_assemble_never_constructs_a_percent_or_a_percentage_point() -> None:
    """The conversion that would put F-005 inside the formatter cannot be written here.

    Reading ``.value`` off either type is fine and is what the formatter does; building
    one is the step that turns a movement into a level, and there is no call that does it.
    """
    constructors = frozenset({"Percent", "PercentagePoints", "pp"})
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno} builds {node.func.id}"
        for path in _modules("assemble")
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in constructors
    ]
    assert not offences, "percent and percentage points never convert (AD-4):\n  " + "\n  ".join(
        offences
    )


# ------------------------------------------------------------------ provenance, AD-6


def test_a_figure_carries_detail_grain_period_country_and_source() -> None:
    """FR-44, all five, and the grain read off the period rather than stored beside it."""
    provenance = a_provenance(country="BHR")
    assert provenance.detail_id == "D-CPI-HEADLINE"
    assert provenance.period == a_period()
    assert provenance.grain is Grain.MONTHLY
    assert provenance.country == "BHR"
    assert provenance.source_id == "S-PSA-CPI"


def test_national_scope_is_the_absence_of_a_country() -> None:
    """AD-5: ``None``, never a blank string something could later filter on."""
    assert a_provenance().is_national
    with pytest.raises(ValueError, match="blank country"):
        a_provenance(country="  ")


def test_a_provenance_with_no_source_is_refused() -> None:
    with pytest.raises(ValueError, match="publishing source"):
        Provenance(detail_id="D-1", period=a_period(), country=None, source_id=" ")


def test_the_source_ref_is_derived_from_the_provenance_and_not_supplied_beside_it() -> None:
    """A reference and the provenance it describes cannot disagree if there is only one."""
    provenance = a_provenance(country="BHR")
    assert provenance.source_ref == "D-CPI-HEADLINE|2026-04|BHR|S-PSA-CPI"
    assert a_provenance().source_ref == "D-CPI-HEADLINE|2026-04||S-PSA-CPI"


def test_an_element_is_built_with_its_class_and_its_source_together() -> None:
    element = measured("Consumer prices rose 2.6% over the year.", a_provenance())
    assert element.element_class is ElementClass.MEASURED
    assert element.source_ref == a_provenance().source_ref


def test_the_class_is_immutable_once_set() -> None:
    """FR-45: set at construction, and there is no later hand that can change it."""
    element = measured("A published row, said in words.", a_provenance())
    with pytest.raises(dataclasses.FrozenInstanceError):
        element.element_class = ElementClass.ARTICLE  # type: ignore[misc]


def test_absent_is_a_class_carrying_content_not_a_missing_element() -> None:
    """At 8% analysis coverage the absence is the common case, so it is said."""
    element = absent("No value is published for this period.", a_provenance())
    assert element.element_class is ElementClass.ABSENT
    assert element.content
    assert element.source_ref


def test_every_class_in_the_vocabulary_can_be_built_with_its_provenance() -> None:
    for element_class in ElementClass:
        element = build("content", element_class, a_provenance())
        assert element.element_class is element_class
        assert element.source_ref == a_provenance().source_ref


# ------------------------------------------------------- provenance enforcement, AD-7


def test_an_element_whose_source_ref_resolves_is_admitted() -> None:
    element = measured("A published row.", a_provenance())
    sources = Resolving(element.source_ref)
    admission = admit(element, sources)
    assert isinstance(admission, Admitted)
    assert admission.element is element


def test_an_element_whose_source_ref_does_not_resolve_is_refused() -> None:
    """AD-7: rejected at the assembler, and never shown unsourced."""
    element = measured("A row nothing in the loaded data backs.", a_provenance())
    admission = admit(element, Resolving())
    assert isinstance(admission, Refused)
    assert isinstance(admission.degradation, Degradation)


def test_the_refusal_is_a_typed_degradation_naming_what_failed_and_where() -> None:
    element = measured("A row nothing in the loaded data backs.", a_provenance())
    admission = admit(element, Resolving())
    assert isinstance(admission, Refused)
    degradation = admission.degradation
    assert degradation.kind == ProvenanceFailure.UNRESOLVED_SOURCE_REF.value
    assert degradation.where == "assemble"
    assert element.source_ref in degradation.detail


def test_a_refusal_is_never_a_silent_drop() -> None:
    """Every element that goes in comes out as an element or as a degradation.

    A silent drop leaves a shorter answer that reads exactly like a complete one, which
    is the failure AD-7 exists to make impossible rather than unlikely.
    """
    good = measured("A published row.", a_provenance())
    bad = measured("An unsourced row.", a_provenance(country="BHR"))
    assembled = admit_all([good, bad, good], Resolving(good.source_ref))
    assert isinstance(assembled, Assembled)
    assert assembled.elements == (good, good)
    assert len(assembled.degradations) == 1
    assert len(assembled.elements) + len(assembled.degradations) == 3


def test_admitting_nothing_yields_nothing_and_no_degradation() -> None:
    assembled = admit_all([], Resolving())
    assert assembled.elements == ()
    assert assembled.degradations == ()


def test_assemble_asks_the_port_and_never_reaches_an_adapter() -> None:
    """The contract in ``pyproject.toml`` owns this; this is the same claim per module,
    so a mis-scoped contract cannot leave it unasserted."""
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno} -> {name}"
        for path in _modules("assemble")
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported_names(node)
        if name.startswith("askai.adapters")
    ]
    assert not offences, "assemble/ reaches an adapter: " + ", ".join(offences)


# ------------------------------------------------------------------ FR-55, trivially


@pytest.mark.parametrize("package", COMPOSING_PACKAGES)
def test_no_figure_is_produced_or_formatted_by_a_language_model(package: str) -> None:
    """FR-55/AD-3, asserted while it is trivially true so that it stops being trivial
    loudly rather than quietly.

    Nothing on the answer path calls a model in this epic. The assertion is written as a
    scan for the import, so the first model client to appear in a composing layer fails
    the build.
    """
    offences = [
        f"{path.relative_to(PACKAGE_ROOT).as_posix()}:{node.lineno} -> {name}"
        for path in _modules(package)
        for node in ast.walk(_parse(path))
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported_names(node)
        if name.split(".")[0] in MODEL_LIBRARIES
    ]
    assert not offences, (
        "no figure is produced, formatted or restated by a language model on the answer "
        "path (FR-55, AD-3): " + ", ".join(offences)
    )


def test_the_elements_the_formatter_produces_are_plain_values() -> None:
    """Nothing in the formatter's output is a callable, a promise, or a model handle."""
    formatter = Formatter(catalogue=load_catalogue(), rule_set=rules())
    written = formatter.format(
        Decimal("2.6"), PublishedFormat(unit="%", spec="0.0"), FormatMode.HEADLINE, Lang.EN
    )
    assert isinstance(written.value, str)
    assert isinstance(written.unit, str)
    assert isinstance(written.decimals, int)
    assert isinstance(measured(written.value, a_provenance()), Element)
