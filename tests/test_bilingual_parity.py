"""Story 10.4 -- the Arabic path measured against the English one.

Story 1.5 already asserts what the *catalogue* owns: the two files carry identical ids,
a counted message carries every form Arabic distinguishes, a composed sentence agrees in
number with its count. None of that is repeated here. What is added is the half 1.5
cannot see:

* **parity as a number over the corpus** -- every capability asked in both languages, and
  the per-capability difference reported rather than felt (FR-60);
* **two finding-families no English test would catch** and no existing test covers:
  first-strong ordering, which decides which way a whole line of Arabic is laid out, and
  the construct state, where a tanwin before a definite noun is ungrammatical.

The Arabic here is character ranges and a bare alef-lam, not wording: the house rule
that keeps reader-facing text in ``messages/data`` is about ``src/askai``, and what this
file needs is the alphabet rather than any sentence written in it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from itertools import pairwise
from pathlib import Path
from typing import Final

import pytest
import yaml

from askai.rules.loader import RuleSet, rules

ROOT: Final = Path(__file__).resolve().parents[1]
CORPUS: Final = ROOT / "corpus"
ARABIC_MESSAGES: Final = ROOT / "src" / "askai" / "messages" / "data" / "ar.yaml"

#: Files whose two languages are not yet balanced, each with the reason it is listed.
#: **It is empty, measured 2026-09-17: every capability is asked the same number of times
#: in each language.** It exists because the next corpus file will be written by an epic
#: that is not this one, and an entry here is a defect that has been seen and costed
#: rather than an exemption -- listed by name, and asserted to still be a real gap.
KNOWN_IMBALANCE: Final[Mapping[str, str]] = {}

#: Strong right-to-left: the Arabic block and its supplements, as the paragraph
#: direction algorithm sees them.
_ARABIC_STRONG: Final = re.compile("[\u0620-\u064A\u066E-\u06D3\u06FA-\u06FF\u0750-\u077F]")
#: Strong left-to-right: a Latin letter is enough to flip a line's direction.
_LATIN_STRONG: Final = re.compile(r"[A-Za-z]")
#: `{value}`, `{unit}` -- removed before reading direction, because what lands in the
#: hole at render time is a figure or a catalogue word, not the placeholder's own name.
_PLACEHOLDER: Final = re.compile(r"\{[^}]*\}")
#: Tanwin: the three case endings a construct-state head may never carry.
_TANWIN: Final = re.compile("[\u064B-\u064D]$")
#: The definite article, alef-lam, at the start of a word.
_DEFINITE: Final = "ال"


@pytest.fixture(scope="module")
def rule_set() -> RuleSet:
    return rules()


def _questions(path: Path) -> list[dict[str, str]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    asked = []
    for entry in document:
        block = entry.get("question")
        if isinstance(block, dict):
            asked.append(block)
    return asked


def _arabic_templates() -> list[tuple[str, str]]:
    """``(message id, template)`` for every string the Arabic catalogue can render."""
    document = yaml.safe_load(ARABIC_MESSAGES.read_text(encoding="utf-8"))
    templates: list[tuple[str, str]] = []
    for message_id, entry in document["messages"].items():
        if isinstance(entry, str):
            templates.append((message_id, entry))
        elif isinstance(entry, dict):
            for form, text in entry.items():
                if isinstance(text, str):
                    templates.append((f"{message_id}.{form}", text))
    return templates


# ------------------------------------------------------------- parity as a number


def test_every_capability_is_asked_in_both_languages(rule_set: RuleSet) -> None:
    """FR-60: parity asserted across the surface, not sampled where someone translated."""
    asked_in_both = "R-PARITY-EVERY-CAPABILITY-IS-ASKED-IN-BOTH"
    assert rule_set.value(asked_in_both, "both_languages_per_capability")
    for path in sorted(CORPUS.glob("epic-*.yaml")):
        asked = _questions(path)
        assert asked, f"{path.name} asks nothing"
        languages = {language for block in asked for language in block}
        assert languages == {"en", "ar"}, f"{path.name} is asked only in {sorted(languages)}"


def test_the_language_gap_is_measured_and_named(rule_set: RuleSet) -> None:
    """The gap is a number per capability, and a non-zero one is a defect with a name.

    The target is zero (`R-PARITY-A-LANGUAGE-GAP-IS-A-DEFECT`). Where a capability is
    not there yet it is listed in `KNOWN_IMBALANCE` with its reason, so the shortfall is
    a countable list that someone has to shorten rather than a tolerance that absorbs
    the next one silently.
    """
    target = rule_set.value("R-PARITY-A-LANGUAGE-GAP-IS-A-DEFECT", "maximum_score_gap_percent")
    assert target == 0

    gaps = {}
    for path in sorted(CORPUS.glob("epic-*.yaml")):
        asked = _questions(path)
        english = sum(1 for block in asked if "en" in block)
        arabic = sum(1 for block in asked if "ar" in block)
        if english != arabic:
            gaps[path.name] = f"{english} English against {arabic} Arabic"

    unexpected = {name: gap for name, gap in gaps.items() if name not in KNOWN_IMBALANCE}
    assert not unexpected, f"a bilingual gap is a defect against FR-60: {unexpected}"
    stale = set(KNOWN_IMBALANCE) - set(gaps)
    assert not stale, f"these are balanced now and the exemption should go: {sorted(stale)}"


def test_the_epic_ten_pair_is_the_same_question_twice() -> None:
    """The parity pair is two entries, deliberately: parity needs two answers to compare."""
    asked = _questions(CORPUS / "epic-10.yaml")
    assert [sorted(block) for block in asked] == [["en"], ["ar"]]


def test_a_cross_language_passage_is_labelled_and_never_translated(rule_set: RuleSet) -> None:
    """Spine open question 8, re-scoped: a rule on SRO and Summary, not a redesign."""
    rule_id = "R-PARITY-A-CROSS-LANGUAGE-PASSAGE-IS-LABELLED"
    assert rule_set.value(rule_id, "fields") == ("sro", "summary")
    assert rule_set.value(rule_id, "label_the_language_of_the_passage") is True
    assert rule_set.value(rule_id, "translate_the_passage") is False
    assert rule_set.value(rule_id, "drop_the_passage_silently") is False


# ------------------------------------------- the finding-family no English test catches


def test_an_arabic_line_is_laid_out_right_to_left_by_its_own_first_word() -> None:
    """First-strong ordering (UBA P2/P3), which no English test can fail.

    A line's direction is taken from its first strong character. An Arabic message that
    opens with a Latin word is rendered left-to-right as a whole -- punctuation at the
    wrong end, the figure in the wrong place -- and every word in it is still spelled
    correctly, which is why review does not catch it. Placeholders are removed first:
    what lands in one is a figure or a catalogue word, never the placeholder's name.
    """
    offenders = []
    for message_id, template in _arabic_templates():
        text = _PLACEHOLDER.sub("", template)
        arabic, latin = _ARABIC_STRONG.search(text), _LATIN_STRONG.search(text)
        if latin is not None and (arabic is None or latin.start() < arabic.start()):
            lead = text[latin.start() : latin.start() + 12]
            offenders.append(f"{message_id}: leads with {lead!r}")
    named = "\n".join(offenders)
    assert not offenders, f"an Arabic message is ordered by its first strong character:\n{named}"


def test_no_arabic_construct_head_carries_a_tanwin() -> None:
    """The genitive construct: a head noun before a definite noun takes no case ending.

    `idafa` is the shape of most of this engine's Arabic noun phrases -- a count and the
    thing counted, an indicator and its scope -- and a tanwin on the head is the error a
    non-speaker cannot see, because the marks are small and the words are right.
    """
    offenders = []
    for message_id, template in _arabic_templates():
        words = _PLACEHOLDER.sub(" ", template).split()
        for head, following in pairwise(words):
            if following.startswith(_DEFINITE) and _TANWIN.search(head):
                offenders.append(f"{message_id}: {head!r} before a definite noun")
    assert not offenders, "a construct-state head takes no tanwin:\n" + "\n".join(offenders)
