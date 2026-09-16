"""What an indicator means -- quoted from the published definition, or stated as absent.

Purity: pure.

FR-33 says a definition *"comes from the published definition, attributed, and is never
generated"*. The measured reality is what makes that harder than it reads: of 289 published
details, **88 carry ``-`` as their English definition and 89 carry it in Arabic**, against
143 distinct English definitions in all. Nearly a third of the catalogue publishes a
placeholder.

A placeholder rendered as a definition is the worst of the three available answers. It is
not generated, so it satisfies FR-33's letter; it is attributed, so it carries provenance;
and it tells the reader that the published definition of their indicator is a hyphen. So
``published_definition`` returns ``None`` for one, and the composer says that none is
published.

**This is the second line, not the first.** FR-64's ``published_text`` already refuses a
placeholder during ingest, so what reaches ``detail.definition_en`` for those 88 rows is
``NULL`` rather than ``-``. That is worth saying here because a reviewer reading the rule
below would otherwise assume it is what stops the hyphen reaching a reader, and would not
look at the ingest when one does. The rule still earns its place: it is what catches a
placeholder spelled a way ``published_text`` does not recognise, and a definition arriving
from anywhere other than that ingest.

**The placeholder list is data**, in ``R-META-PLACEHOLDER-IS-NOT-A-DEFINITION``, because
the next export will spell one a new way and that should be a file edit. It is compared
under the engine's single ``normalise``, so a placeholder with a different dash, different
whitespace or a different case is the same placeholder -- and there is no second fold here
doing it differently.

**Absence in one language is stated, not filled from the other** (FR-60). An Arabic reader
whose indicator publishes only an English definition is told none is published in Arabic.
Substituting would answer a question about the Arabic catalogue with the English one,
silently, and the reader has no way to see it happened.
"""

from __future__ import annotations

from enum import StrEnum

from askai.assemble.meta.reference import CatalogueReference, ReferenceKind, catalogue_element
from askai.assemble.roles import Placed, Role
from askai.domain.element import ElementClass
from askai.domain.normalise import normalise
from askai.messages import Catalogue, Lang, render
from askai.ports.groups import PublishedDefinition
from askai.rules import RuleSet

__all__ = [
    "DefinitionClause",
    "DefinitionMessage",
    "DefinitionRule",
    "definition_element",
    "published_definition",
]


class DefinitionMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    PUBLISHED = "definition.published"
    NONE_PUBLISHED = "definition.none_published"


class DefinitionRule(StrEnum):
    """The rule ids this module reads. Ids, not values -- the values stay in the file."""

    PLACEHOLDER = "R-META-PLACEHOLDER-IS-NOT-A-DEFINITION"


class DefinitionClause(StrEnum):
    """The clause names read off those rules."""

    PLACEHOLDER_SPELLINGS = "placeholder_spellings"


class DefinitionError(LookupError):
    """The placeholder table cannot be acted on.

    Raised rather than defaulted to an empty list. An empty placeholder table would render
    ``-`` to a third of the catalogue's readers as their indicator's published meaning,
    which is the precise failure the table exists to prevent -- so a malformed table stops
    the answer instead of disabling the check.
    """


def published_definition(
    rule_set: RuleSet, definition: PublishedDefinition, lang: Lang
) -> str | None:
    """The definition to quote in *lang*, or ``None`` when none is published.

    ``None`` covers both ways a definition can be missing -- blank, and a placeholder --
    because they are the same fact about the catalogue and a caller that had to tell them
    apart would eventually get one of them wrong. What ``None`` never covers is *no such
    detail*: the port returns ``None`` for that, one layer earlier, and the two reach the
    reader as different sentences.
    """
    match lang:
        case Lang.EN:
            published = definition.definition_en
        case Lang.AR:
            published = definition.definition_ar
    text = published.strip()
    if not text or normalise(text) in _placeholders(rule_set):
        return None
    return text


def definition_element(
    catalogue: Catalogue,
    lang: Lang,
    rule_set: RuleSet,
    definition: PublishedDefinition,
    detail_name: str,
) -> Placed:
    """The published definition of *detail_name*, quoted -- or the statement that none is.

    Role ``evidence`` in both cases: a definition is published content shown as published,
    and the statement that none exists sits in the same place so a reader who expected one
    finds the answer where they looked.

    The two classes differ, and that is the whole record of what happened. ``measured`` is
    the published text, carried through unaltered. ``absent`` is *"no definition is
    published"* -- content, not a missing element, which is what keeps the answer from
    being silently shorter for the third of the catalogue that publishes a placeholder.
    """
    reference = CatalogueReference(kind=ReferenceKind.DETAIL, key=definition.detail_id)
    quoted = published_definition(rule_set, definition, lang)
    if quoted is None:
        content = render(
            catalogue, lang, DefinitionMessage.NONE_PUBLISHED.value, detail=detail_name
        )
        return Placed(
            element=catalogue_element(content, ElementClass.ABSENT, reference),
            role=Role.EVIDENCE,
        )
    content = render(
        catalogue,
        lang,
        DefinitionMessage.PUBLISHED.value,
        detail=detail_name,
        definition=quoted,
    )
    return Placed(
        element=catalogue_element(content, ElementClass.MEASURED, reference),
        role=Role.EVIDENCE,
    )


def _placeholders(rule_set: RuleSet) -> frozenset[str]:
    """The placeholder spellings, folded once through the engine's single ``normalise``.

    Folded here rather than in the file so the file stays readable -- a reviewer sees
    ``-`` and ``n/a``, not their normal forms -- and so the comparison uses the same fold
    every other text comparison in the engine uses.
    """
    value = rule_set.value(
        DefinitionRule.PLACEHOLDER.value, DefinitionClause.PLACEHOLDER_SPELLINGS.value
    )
    if not isinstance(value, tuple):
        raise DefinitionError(
            f"{DefinitionRule.PLACEHOLDER.value} value "
            f"`{DefinitionClause.PLACEHOLDER_SPELLINGS.value}` must be a list of "
            f"spellings, not {type(value).__name__}; without it a placeholder would be "
            "quoted to a reader as their indicator's published meaning"
        )
    return frozenset(normalise(spelling) for spelling in value)
