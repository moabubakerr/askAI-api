"""Arabic counts do not pluralise as English does (R-174).

Purity: data, imports only ``messages/lang``.

English has two shapes for a counted noun; Arabic has six, and four of them are
distinctions English simply does not make::

    1   ->  مؤشر واحد        singular
    2   ->  مؤشران            the dual -- a form, not "two" plus a plural
    3   ->  3 مؤشرات          the 3-10 plural of paucity
    11  ->  11 مؤشرًا          singular accusative again, from 11 upward

A translation layer over an English answer cannot produce that: by the time the
English sentence exists, the dual has already been thrown away. So the category is
computed from the count *and the language together*, before any wording is chosen,
and the catalogue supplies one form per category.

The Arabic rule below is the full CLDR one rather than the four cases R-174 quotes,
because the quoted cases are the head of a rule that keeps going: it is the **last two
digits** that decide, so 103 is *few* and 111 is *many* while 100 is *other*. Stopping
at "11+ is singular accusative" would be right for 11 through 99 and wrong from 100 on
-- a defect that only appears on the larger counts, which are exactly the ones nobody
writes a test for by hand.

``REQUIRED_CATEGORIES`` is what the loader validates each counted message against, so
an Arabic message missing its dual fails to start rather than falling back to a plural
that reads as a mistake to every Arabic speaker who sees it.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from askai.messages.lang import Lang

__all__ = ["REQUIRED_CATEGORIES", "PluralCategory", "plural_category"]


class PluralCategory(StrEnum):
    """A plural form a language distinguishes. CLDR's names, so the data is reviewable
    against a published standard rather than against this module."""

    ZERO = "zero"
    ONE = "one"
    TWO = "two"
    FEW = "few"
    MANY = "many"
    OTHER = "other"


#: The categories each language's rule below can actually return. A counted message
#: must supply exactly these -- no fewer, so nothing falls back; no more, so a form
#: that can never be selected is not left in the catalogue looking maintained.
REQUIRED_CATEGORIES: Final[Mapping[Lang, frozenset[PluralCategory]]] = MappingProxyType(
    {
        Lang.EN: frozenset({PluralCategory.ONE, PluralCategory.OTHER}),
        Lang.AR: frozenset(PluralCategory),
    }
)


def plural_category(lang: Lang, count: int) -> PluralCategory:
    """Which form *lang* uses for *count*.

    Exhaustive on ``Lang`` on purpose: a language added later must state its rule here
    before it can be rendered, rather than silently inheriting English's two forms --
    which is precisely the "Arabic as a translation layer" failure FR-62 names.
    """
    if not isinstance(count, int) or isinstance(count, bool):
        # `bool` is an `int`, and `True` would quietly render as the singular of
        # something that was never counted.
        raise TypeError(f"count must be an int, not {type(count).__name__}")
    if count < 0:
        # A count of things the engine found cannot be negative, and there is no
        # agreed Arabic form for one, so this is a caller defect rather than a
        # rendering choice to be made here.
        raise ValueError(f"count must not be negative, got {count}")

    match lang:
        case Lang.EN:
            return PluralCategory.ONE if count == 1 else PluralCategory.OTHER
        case Lang.AR:
            return _arabic_category(count)
        case _:
            raise TypeError(
                f"{lang!r} is not a Lang, or is one whose plural rule has not been "
                "written; state how it counts before rendering in it"
            )


def _arabic_category(count: int) -> PluralCategory:
    if count == 0:
        return PluralCategory.ZERO
    if count == 1:
        return PluralCategory.ONE
    if count == 2:
        return PluralCategory.TWO
    # The last two digits carry the rule from here on, which is why 103 counts as
    # 3 does and 111 as 11 does.
    last_two = count % 100
    if 3 <= last_two <= 10:
        return PluralCategory.FEW
    if 11 <= last_two <= 99:
        return PluralCategory.MANY
    return PluralCategory.OTHER
