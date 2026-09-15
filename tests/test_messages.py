"""Story 1.5 -- the bilingual message catalogue.

What is asserted here, and why each one is worth a test:

* the two language files agree on which messages exist, and the loader **fails to
  start** when they do not -- in both directions, and for a message that is counted in
  one language and not the other;
* Arabic counts take the six forms R-174 names, including the dual and the 3-10 plural
  English does not distinguish, and the 11+ singular;
* a composed sentence agrees in number with its count and names the unit it was given,
  not one of its own (R-175);
* ``Lang`` is an explicit argument on every rendering path -- checked by signature, so
  a default added later fails rather than being noticed in review;
* no reader-facing string literal exists in ``askai/`` outside ``messages/``.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from askai.domain.period import Period
from askai.messages import (
    Catalogue,
    CatalogueError,
    Counted,
    Lang,
    Plain,
    PluralCategory,
    compose_counted,
    format_value,
    load_catalogue,
    plural_category,
    render,
    render_counted,
    render_period,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "askai"
MESSAGES = SRC / "messages"


@pytest.fixture(scope="module")
def catalogue() -> Catalogue:
    return load_catalogue()


# --------------------------------------------------------------------------- parity


def test_both_language_files_ship_with_the_package() -> None:
    for lang in Lang:
        assert (MESSAGES / "data" / f"{lang.value}.yaml").is_file()


def test_the_two_files_are_keyed_by_identical_message_ids(catalogue: Catalogue) -> None:
    by_lang = {lang: frozenset(catalogue.entries[lang]) for lang in Lang}
    assert by_lang[Lang.EN] == by_lang[Lang.AR]
    assert by_lang[Lang.EN]  # a catalogue with nothing in it would pass the line above


def test_an_id_is_the_same_kind_in_both_languages(catalogue: Catalogue) -> None:
    for message_id, entry in catalogue.entries[Lang.EN].items():
        assert type(entry) is type(catalogue.entries[Lang.AR][message_id]), message_id


def test_arabic_counted_messages_carry_every_form_arabic_distinguishes(
    catalogue: Catalogue,
) -> None:
    counted = [
        (message_id, entry)
        for message_id, entry in catalogue.entries[Lang.AR].items()
        if isinstance(entry, Counted)
    ]
    assert counted, "the catalogue should exercise counted messages"
    for message_id, entry in counted:
        assert frozenset(entry.forms) == frozenset(PluralCategory), message_id


# ------------------------------------------------------- the loader refuses to start


def _write(directory: Path, lang: str, messages: str, *, numbers: str | None = None) -> None:
    block = numbers or (
        'digits: "0123456789"\n  group_separator: ","\n'
        '  decimal_separator: "."\n  group_size: 3'
    )
    (directory / f"{lang}.yaml").write_text(
        f"version: 1\nnumbers:\n  {block}\nmessages:\n{messages}\n", encoding="utf-8"
    )


def _pair(directory: Path, english: str, arabic: str) -> Path:
    _write(directory, "en", english)
    _write(directory, "ar", arabic)
    return directory


def test_a_key_in_one_language_and_not_the_other_stops_startup(tmp_path: Path) -> None:
    root = _pair(tmp_path, '  label.unit: "Unit"\n  label.source: "Source"', '  label.unit: "x"')
    with pytest.raises(CatalogueError, match="disagree on which messages exist"):
        load_catalogue(root)


def test_the_check_runs_in_both_directions(tmp_path: Path) -> None:
    root = _pair(tmp_path, '  label.unit: "Unit"', '  label.unit: "x"\n  label.source: "y"')
    with pytest.raises(CatalogueError) as raised:
        load_catalogue(root)
    assert "label.source" in str(raised.value)


def test_counted_in_one_language_and_plain_in_the_other_stops_startup(tmp_path: Path) -> None:
    root = _pair(
        tmp_path,
        '  count.thing:\n    one: "{count} thing"\n    other: "{count} things"',
        '  count.thing: "شيء"',
    )
    with pytest.raises(CatalogueError, match="counted in one language and not in another"):
        load_catalogue(root)


def test_an_arabic_message_without_its_dual_stops_startup(tmp_path: Path) -> None:
    """The failure R-174 exists to prevent: a dual silently served as a plural."""
    root = _pair(
        tmp_path,
        '  count.thing:\n    one: "{count} thing"\n    other: "{count} things"',
        (
            '  count.thing:\n    zero: "a"\n    one: "b"\n    few: "c"\n'
            '    many: "d"\n    other: "e"'
        ),
    )
    with pytest.raises(CatalogueError, match="missing \\['two'\\]"):
        load_catalogue(root)


def test_a_form_english_cannot_select_stops_startup(tmp_path: Path) -> None:
    root = _pair(
        tmp_path,
        '  count.thing:\n    one: "a"\n    two: "b"\n    other: "c"',
        (
            '  count.thing:\n    zero: "a"\n    one: "b"\n    two: "z"\n    few: "c"\n'
            '    many: "d"\n    other: "e"'
        ),
    )
    with pytest.raises(CatalogueError, match="unusable \\['two'\\]"):
        load_catalogue(root)


def test_a_missing_language_file_stops_startup(tmp_path: Path) -> None:
    _write(tmp_path, "en", '  label.unit: "Unit"')
    with pytest.raises(CatalogueError, match="missing or unreadable"):
        load_catalogue(tmp_path)


def test_a_version_this_build_does_not_read_stops_startup(tmp_path: Path) -> None:
    root = _pair(tmp_path, '  label.unit: "Unit"', '  label.unit: "x"')
    (root / "ar.yaml").write_text(
        'version: 99\nnumbers:\n  digits: "0123456789"\n  group_separator: ","\n'
        '  decimal_separator: "."\n  group_size: 3\nmessages:\n  label.unit: "x"\n',
        encoding="utf-8",
    )
    with pytest.raises(CatalogueError, match="declares version 99"):
        load_catalogue(root)


def test_a_substitution_that_reaches_into_a_parameter_stops_startup(tmp_path: Path) -> None:
    root = _pair(tmp_path, '  a: "{spec.period}"', '  a: "{spec.period}"')
    with pytest.raises(CatalogueError, match="does not index or reach into one"):
        load_catalogue(root)


def test_an_uncounted_message_may_not_use_the_counted_fields(tmp_path: Path) -> None:
    root = _pair(tmp_path, '  a: "{counted} found"', '  a: "{counted}"')
    with pytest.raises(CatalogueError, match="only a counted message receives"):
        load_catalogue(root)


def test_invalid_yaml_stops_startup(tmp_path: Path) -> None:
    (tmp_path / "en.yaml").write_text("version: 1\n  : :\n", encoding="utf-8")
    (tmp_path / "ar.yaml").write_text("version: 1\n", encoding="utf-8")
    with pytest.raises(CatalogueError):
        load_catalogue(tmp_path)


# ------------------------------------------------------------- R-174 pluralisation


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, PluralCategory.ZERO),
        (1, PluralCategory.ONE),
        (2, PluralCategory.TWO),
        (3, PluralCategory.FEW),
        (10, PluralCategory.FEW),
        (11, PluralCategory.MANY),
        (99, PluralCategory.MANY),
        (100, PluralCategory.OTHER),
        (101, PluralCategory.OTHER),
        (102, PluralCategory.OTHER),
        (103, PluralCategory.FEW),
        (111, PluralCategory.MANY),
        (200, PluralCategory.OTHER),
    ],
)
def test_the_arabic_plural_rule_is_decided_by_the_last_two_digits(
    count: int, expected: PluralCategory
) -> None:
    assert plural_category(Lang.AR, count) is expected


def test_english_distinguishes_two_forms_where_arabic_distinguishes_six() -> None:
    english = {plural_category(Lang.EN, n) for n in range(205)}
    arabic = {plural_category(Lang.AR, n) for n in range(205)}
    assert english == {PluralCategory.ONE, PluralCategory.OTHER}
    assert arabic == set(PluralCategory)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "مؤشر واحد"),
        (2, "مؤشران"),
        (3, "3 مؤشرات"),
        (10, "10 مؤشرات"),
        (11, "11 مؤشرًا"),
        (99, "99 مؤشرًا"),
        (100, "100 مؤشر"),
        (103, "103 مؤشرات"),
    ],
)
def test_the_arabic_counted_noun_takes_the_form_its_count_selects(
    catalogue: Catalogue, count: int, expected: str
) -> None:
    assert render_counted(catalogue, Lang.AR, "count.indicator", count) == expected


def test_the_dual_is_a_form_and_not_two_plus_a_plural(catalogue: Catalogue) -> None:
    """The distinction English does not make at all: 2 is not 3 with a different digit."""
    two = render_counted(catalogue, Lang.AR, "count.indicator", 2)
    three = render_counted(catalogue, Lang.AR, "count.indicator", 3)
    assert two != three
    assert "2" not in two  # the dual spells the count into the noun
    assert render_counted(catalogue, Lang.EN, "count.indicator", 2) == "2 indicators"
    assert render_counted(catalogue, Lang.EN, "count.indicator", 3) == "3 indicators"


def test_every_counted_noun_renders_in_both_languages_at_every_boundary(
    catalogue: Catalogue,
) -> None:
    nouns = [
        message_id
        for message_id, entry in catalogue.entries[Lang.AR].items()
        if isinstance(entry, Counted) and message_id.startswith("count.")
    ]
    assert nouns
    for message_id in nouns:
        rendered = {
            (lang, n): render_counted(catalogue, lang, message_id, n)
            for lang in Lang
            for n in (0, 1, 2, 3, 10, 11, 100, 103)
        }
        assert all(rendered.values()), message_id
        # Arabic must not collapse the four counts English writes identically.
        arabic = {rendered[(Lang.AR, n)] for n in (1, 2, 3, 11)}
        assert len(arabic) == 4, message_id


def test_a_negative_count_is_refused_rather_than_rendered() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        plural_category(Lang.AR, -1)


# ------------------------------------------------------------------ R-175 sentences


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (0, "لم نجد مؤشرات تطابق سؤالك."),
        (1, "وجدنا مؤشر واحد يطابق سؤالك."),
        (2, "وجدنا مؤشران يطابقان سؤالك."),
        (3, "وجدنا 3 مؤشرات تطابق سؤالك."),
        (11, "وجدنا 11 مؤشرًا يطابق سؤالك."),
    ],
)
def test_a_composed_sentence_agrees_in_number_with_the_count_it_carries(
    catalogue: Catalogue, count: int, expected: str
) -> None:
    sentence = compose_counted(catalogue, Lang.AR, "sentence.found", "count.indicator", count)
    assert sentence == expected


def test_the_sentence_and_the_noun_are_selected_by_the_same_count(
    catalogue: Catalogue,
) -> None:
    """The dual changes the verb as well as the noun -- the failure R-175 names."""
    one = compose_counted(catalogue, Lang.AR, "sentence.found", "count.indicator", 1)
    two = compose_counted(catalogue, Lang.AR, "sentence.found", "count.indicator", 2)
    few = compose_counted(catalogue, Lang.AR, "sentence.found", "count.indicator", 3)
    assert len({one, two, few}) == 3
    # The verb differs, not only the noun that was substituted in.
    assert one.replace("مؤشر واحد", "") != two.replace("مؤشران", "")


def test_the_sentence_names_the_unit_it_was_given(catalogue: Catalogue) -> None:
    """R-175's other half: the unit is the reader's, passed in, never chosen here."""
    years = compose_counted(catalogue, Lang.AR, "sentence.found", "count.year", 2)
    months = compose_counted(catalogue, Lang.AR, "sentence.found", "count.month", 2)
    assert "سنتان" in years
    assert "شهران" in months
    assert years != months
    english = compose_counted(catalogue, Lang.EN, "sentence.found", "count.quarter", 2)
    assert english == "We found 2 quarters that match your question."


def test_a_composed_sentence_still_takes_its_other_parameters(catalogue: Catalogue) -> None:
    rendered = compose_counted(
        catalogue, Lang.EN, "sentence.available_for", "count.datapoint", 1, detail="Inflation"
    )
    assert rendered == "1 data point is available for Inflation."
    arabic = compose_counted(
        catalogue, Lang.AR, "sentence.available_for", "count.datapoint", 2, detail="التضخم"
    )
    assert arabic == "نقطتا بيانات متاحان لـالتضخم."


# ---------------------------------------------------------------------- FR-62 numbers


@pytest.mark.parametrize(
    ("lang", "value", "expected"),
    [
        (Lang.EN, 1234567, "1,234,567"),
        (Lang.AR, 1234567, "1٬234٬567"),
        (Lang.EN, Decimal("1234.56"), "1,234.56"),
        (Lang.AR, Decimal("1234.56"), "1٬234٫56"),
        (Lang.EN, Decimal("-0.5"), "-0.5"),
        (Lang.AR, Decimal("-0.5"), "-0٫5"),
        (Lang.EN, 0, "0"),
        (Lang.AR, Decimal("1E+3"), "1٬000"),
    ],
)
def test_numbers_follow_the_language_s_own_conventions(
    catalogue: Catalogue, lang: Lang, value: int | Decimal, expected: str
) -> None:
    assert format_value(catalogue, lang, value) == expected


def test_a_float_never_reaches_a_rendered_figure(catalogue: Catalogue) -> None:
    with pytest.raises(TypeError, match="already lost the published value"):
        format_value(catalogue, Lang.AR, 1.5)  # type: ignore[arg-type]


# ----------------------------------------------------------------- FR-62 period forms


@pytest.mark.parametrize(
    ("period", "english", "arabic"),
    [
        ("2025", "2025", "2025"),
        ("2025-Q1", "Q1 2025", "الربع الأول 2025"),
        ("2025-03", "March 2025", "مارس 2025"),
        ("2024-12", "December 2024", "ديسمبر 2024"),
    ],
)
def test_a_period_is_written_in_the_language_s_own_form(
    catalogue: Catalogue, period: str, english: str, arabic: str
) -> None:
    assert render_period(catalogue, Lang.EN, Period(period)) == english
    assert render_period(catalogue, Lang.AR, Period(period)) == arabic


def test_a_year_is_a_label_and_is_not_grouped(catalogue: Catalogue) -> None:
    assert render_period(catalogue, Lang.AR, Period("2025")) == "2025"


# --------------------------------------------------------------- rendering discipline


def test_a_missing_parameter_is_refused_rather_than_left_as_a_hole(
    catalogue: Catalogue,
) -> None:
    with pytest.raises(CatalogueError, match="missing"):
        render(catalogue, Lang.EN, "clarify.which_period")


def test_a_surplus_parameter_is_refused(catalogue: Catalogue) -> None:
    with pytest.raises(CatalogueError, match="not used"):
        render(catalogue, Lang.EN, "clarify.which_period", detail="x", stale="y")


def test_an_unknown_message_id_is_refused_rather_than_echoed(catalogue: Catalogue) -> None:
    with pytest.raises(CatalogueError, match="no message"):
        render(catalogue, Lang.AR, "no.such.message")


def test_a_counted_message_is_not_rendered_as_a_plain_one(catalogue: Catalogue) -> None:
    with pytest.raises(CatalogueError, match="render it with render_counted"):
        render(catalogue, Lang.AR, "count.indicator")
    with pytest.raises(CatalogueError, match="render it with render"):
        render_counted(catalogue, Lang.AR, "label.unit", 2)


def test_the_same_catalogue_serves_both_languages(catalogue: Catalogue) -> None:
    """One loaded catalogue, two languages -- the language is on the call, not the load."""
    assert render(catalogue, Lang.EN, "label.unit") != render(catalogue, Lang.AR, "label.unit")


# -------------------------------------------------- Lang is explicit, never inferred


def _public_callables() -> Iterator[tuple[str, Any]]:
    import askai.messages as package

    for name in package.__all__:
        member = getattr(package, name)
        if callable(member) and not isinstance(member, type):
            yield name, member


def test_lang_is_an_argument_on_every_rendering_path() -> None:
    rendering = {"render", "render_counted", "compose_counted", "render_period", "format_value"}
    for name, member in _public_callables():
        if name not in rendering:
            continue
        parameters = list(inspect.signature(member).parameters.values())
        assert any(p.annotation in (Lang, "Lang") for p in parameters), name


def test_no_rendering_path_defaults_its_language() -> None:
    """A default would be the global arriving under another name (AD-11, FR-61)."""
    for name, member in _public_callables():
        for parameter in inspect.signature(member).parameters.values():
            if parameter.annotation in (Lang, "Lang"):
                assert parameter.default is inspect.Parameter.empty, f"{name}.{parameter.name}"


def test_the_package_holds_no_module_level_language() -> None:
    for module in sorted(MESSAGES.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                assert not (
                    isinstance(target, ast.Name) and target.id.lower() in {"lang", "language"}
                ), f"{module.name}: a module-level language is the global AD-11 forbids"


# ------------------------------------- no reader-facing string literal outside messages/
#
# Scope, stated plainly because it matters: this scan targets **Arabic-script literals**
# rather than trying to tell an English reader sentence from an English developer one.
# A heuristic over English text cannot distinguish `"That is not in the published data"`
# from a message raised to a developer, and a flaky architecture test is worse than a
# narrow one.
#
# Arabic is the sharp edge of the same rule and the one that actually bites: an Arabic
# *word* in this engine is by construction something a reader sees, so one anywhere in
# `askai/` -- including inside `messages/` itself, where the Python modules are
# machinery and the words live in YAML -- is reader-facing text written at the point of
# use. Docstrings and comments are excluded on purpose: they document behaviour and are
# not rendered. Single-character literals are excluded too, and that is the only
# exemption: a lone Arabic character is a normalisation or character-class entry
# (`domain/normalise.py` is made of them), never something anyone reads.
#
# The complementary half is asserted structurally: the only catalogue files are the two
# under `messages/data/`, so there is no second place for wording to live.

_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")

_Scoped = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


def _literals(source: str) -> Iterator[tuple[int, str]]:
    """Every string literal in *source* that is not a docstring."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, _Scoped)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            yield node.lineno, node.value


def _python_sources() -> list[Path]:
    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)


def test_no_reader_facing_literal_appears_in_askai_outside_the_catalogue() -> None:
    offenders: list[str] = []
    for path in _python_sources():
        for line, literal in _literals(path.read_text(encoding="utf-8")):
            if len(literal.strip()) > 1 and _ARABIC.search(literal):
                offenders.append(f"{path.relative_to(SRC)}:{line}: {literal!r}")
    assert not offenders, (
        "reader-facing text belongs in messages/data, not in code:\n" + "\n".join(offenders)
    )


def test_the_catalogue_is_the_only_place_wording_lives() -> None:
    """One reviewable artifact (FR-63a): two files, and no third copy to drift from."""
    data = sorted(p.name for p in (MESSAGES / "data").iterdir() if p.is_file())
    assert data == ["ar.yaml", "en.yaml"]
    elsewhere = [
        path.relative_to(SRC)
        for path in SRC.rglob("*.yaml")
        if path.name in {"en.yaml", "ar.yaml"} and path.parent != MESSAGES / "data"
    ]
    assert not elsewhere, f"a second catalogue would drift from the first: {elsewhere}"


def test_the_english_file_carries_no_arabic_and_the_arabic_file_does() -> None:
    """A guard against a paste that leaves one language's wording in the other's file."""
    english = (MESSAGES / "data" / "en.yaml").read_text(encoding="utf-8")
    arabic = (MESSAGES / "data" / "ar.yaml").read_text(encoding="utf-8")
    english_messages = english.split("messages:", 1)[1]
    assert not _ARABIC.search(english_messages)
    assert _ARABIC.search(arabic)


def test_every_message_is_reachable_and_renders_in_both_languages(
    catalogue: Catalogue,
) -> None:
    """Nothing in the catalogue is unrenderable -- a form nobody can reach is a defect
    the review of the file cannot see."""
    for message_id, entry in catalogue.entries[Lang.EN].items():
        params = {field: "x" for field in catalogue.parameters(message_id)}
        for lang in Lang:
            if isinstance(entry, Plain):
                assert render(catalogue, lang, message_id, **params)
            elif "sentence." in message_id:
                assert compose_counted(
                    catalogue, lang, message_id, "count.indicator", 3, **params
                )
            else:
                assert render_counted(catalogue, lang, message_id, 3, **params)
