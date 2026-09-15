"""Every rendering path, and ``Lang`` is an argument on all of them.

Purity: data; imports ``messages/`` and ``domain/`` and nothing above them.

Four entry points, and no fifth:

``render``            a message that does not depend on a count.
``render_counted``    a counted noun, agreeing with its count (R-174).
``compose_counted``   a sentence agreeing with the count it carries, naming the unit
                      the reader asked in (R-175).
``render_period``     a period written in the language's own period form (FR-62).

``lang`` is the second positional parameter of each, it has no default, and nothing in
this module reads a process-wide, request-wide or thread-local language. That is the
whole of AD-11's language rule: a call site that has not been handed a language cannot
render, so "answer in the language of the question" fails loudly at the point the
language went missing rather than quietly answering in English.

**R-175 is why ``compose_counted`` exists as a separate function.** A sentence about a
count has two things to agree with, not one. The noun takes the form its count selects
-- ``مؤشران`` for two -- and the sentence around it takes the agreement that same count
selects, which in Arabic is a different word for the dual than for three. Rendering the
noun and then interpolating it into a fixed sentence would get the first right and the
second wrong, in a way that reads as broken Arabic while every unit test on the noun
passes. So the count selects the form of both, together, from one call.

The other half of R-175 is ``unit_id``: the unit is an argument, chosen by what the
reader asked in, never by what the engine happens to store. There is no default unit
here for the same reason there is no default language.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from askai.domain.period import Grain, Period
from askai.messages.catalogue import Catalogue, CatalogueError, Counted, Entry, Plain
from askai.messages.lang import Lang
from askai.messages.numbers import format_number as _format
from askai.messages.plural import plural_category

__all__ = [
    "compose_counted",
    "format_value",
    "render",
    "render_counted",
    "render_period",
]

# The period forms, one message id per grain, so a language writes a quarter the way it
# writes a quarter rather than the way English does with the words swapped. Read-only,
# because a module-level dict in this engine is the shape an ambient collector takes.
_PERIOD_MESSAGE: Final[Mapping[Grain, str]] = MappingProxyType(
    {
        Grain.YEARLY: "period.yearly",
        Grain.QUARTERLY: "period.quarterly",
        Grain.MONTHLY: "period.monthly",
    }
)


def render(catalogue: Catalogue, lang: Lang, message_id: str, /, **params: object) -> str:
    """Render the uncounted message *message_id* in *lang*."""
    entry = catalogue.entry(lang, message_id)
    if not isinstance(entry, Plain):
        raise CatalogueError(
            f"{message_id!r} is a counted message; render it with render_counted so it "
            "agrees with its count"
        )
    _check_params(catalogue, message_id, params, supplied=frozenset())
    return _substitute(entry.text, params)


def render_counted(
    catalogue: Catalogue, lang: Lang, message_id: str, count: int, /, **params: object
) -> str:
    """Render *message_id* in the form *lang* uses for *count*.

    The formatted count is available to the template as ``{count}`` and is not asked of
    the caller, because a form that writes the numeral and a form that does not are the
    same message -- Arabic's ``مؤشر واحد`` spells the one out and carries no digit.
    """
    entry = catalogue.entry(lang, message_id)
    template = _form(entry, lang, message_id, count)
    _check_params(catalogue, message_id, params, supplied=frozenset({"count"}))
    return _substitute(template, {**params, "count": format_value(catalogue, lang, count)})


def compose_counted(
    catalogue: Catalogue,
    lang: Lang,
    sentence_id: str,
    unit_id: str,
    count: int,
    /,
    **params: object,
) -> str:
    """Render *sentence_id* around *count* of *unit_id*, both agreeing with the count.

    *unit_id* names the counted noun the reader asked in -- the unit on the question,
    not the unit the figure is stored in (R-175). Passing it is the only way to say it,
    which is the point.
    """
    counted = render_counted(catalogue, lang, unit_id, count)
    sentence = catalogue.entry(lang, sentence_id)
    template = _form(sentence, lang, sentence_id, count)
    _check_params(catalogue, sentence_id, params, supplied=frozenset({"count", "counted"}))
    return _substitute(
        template,
        {**params, "counted": counted, "count": format_value(catalogue, lang, count)},
    )


def render_period(catalogue: Catalogue, lang: Lang, period: Period, /) -> str:
    """Write *period* in *lang*'s period form.

    The grain is read off the period (AD: ``Period`` owns its grain) rather than taken
    as an argument, so there is no call that can write a quarter in the yearly form.
    Years are substituted as bare digits and not through ``format_value``: 2025 is a
    label, and grouping it into "2,025" would be the formatter treating a name as a
    quantity.
    """
    entry_id = _PERIOD_MESSAGE[period.grain]
    match period.grain:
        case Grain.YEARLY:
            return render(catalogue, lang, entry_id, year=period.value)
        case Grain.QUARTERLY:
            year, quarter = period.value.split("-Q")
            return render(
                catalogue,
                lang,
                entry_id,
                year=year,
                quarter=render(catalogue, lang, f"period.quarter.{int(quarter)}"),
            )
        case Grain.MONTHLY:
            year, month = period.value.split("-")
            return render(
                catalogue,
                lang,
                entry_id,
                year=year,
                month=render(catalogue, lang, f"period.month.{int(month)}"),
            )
        case _:
            raise CatalogueError(
                f"{period.grain!r} has no period form in the catalogue; a grain the "
                "engine reads is a grain it must be able to write"
            )


def format_value(catalogue: Catalogue, lang: Lang, value: int | Decimal, /) -> str:
    """Write *value* with *lang*'s numerals and separators, as declared in the data."""
    return _format(catalogue.numbers[lang], value)


def _form(entry: Entry, lang: Lang, message_id: str, count: int) -> str:
    if not isinstance(entry, Counted):
        raise CatalogueError(
            f"{message_id!r} is not a counted message; it has one wording, so render it "
            "with render"
        )
    category = plural_category(lang, count)
    # The loader has already refused a message missing a form its language can select,
    # so a miss here would mean the catalogue was mutated after loading.
    return entry.forms[category]


def _check_params(
    catalogue: Catalogue, message_id: str, params: dict[str, object], supplied: frozenset[str]
) -> None:
    """Exactly the message's parameters, no more and no fewer.

    Strict in both directions deliberately. A missing one is a hole in a sentence; a
    surplus one is almost always a renamed field where the call site was not renamed
    with it, and silently ignoring it is how a sentence keeps rendering with last
    month's value in it.
    """
    required = catalogue.parameters(message_id) - supplied
    given = frozenset(params)
    if given == required:
        return
    missing = sorted(required - given)
    unused = sorted(given - required)
    raise CatalogueError(
        f"message {message_id!r} takes {sorted(required)}; missing "
        f"{missing or 'nothing'}, not used {unused or 'nothing'}"
    )


def _substitute(template: str, params: dict[str, object]) -> str:
    # `format_map` rather than `%` or f-string assembly: the loader has already checked
    # every field is a plain name, so this cannot reach into an object.
    try:
        return template.format_map(params)
    except KeyError as exc:
        # Reachable for `{counted}` on a message rendered without a composed sentence:
        # the field is reserved, so it is not asked of the caller, and only
        # `compose_counted` supplies it.
        raise CatalogueError(
            f"the template needs {exc.args[0]!r}, which this rendering path does not "
            "supply; a sentence naming {counted} is composed with compose_counted"
        ) from None
