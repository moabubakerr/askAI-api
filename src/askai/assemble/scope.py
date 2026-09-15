"""The ``scope`` element -- the answer saying what it did.

Purity: pure. Every word comes from ``messages/``; the period form, the grain word, the
country phrase and the punctuation between them are all ids in the two catalogue files.

FR-56: *"The answer states what it did: which grain, which periods, which countries,
which basis. The reader should never have to guess what was compared with what."* The
response already echoes the ``QuerySpec`` -- that is what the corpus asserts on and what
the record stores -- but a spec block is a machine artifact. The reader-facing half is
this element, of role ``scope``, reading *"monthly, National, April 2026"*.

Three decisions, and each has a defect behind it.

**Composed, never dumped.** AD-23: *"Element text is composed server-side, so the
bilingual catalogue remains the only source of reader-facing strings."* The temptation
is to serialise the spec and let the client label it, which puts reader-facing wording
in a client, in one language, outside the reviewable artifact. So the statement is built
from message ids here, and it renders in Arabic because Arabic is authored beside it --
not because an English sentence was translated at the edge.

**The grain is read off the period.** A period owns its grain, so the statement takes a
``Provenance`` and asks it; there is no signature here carrying both, and therefore no
way to state a grain the period does not have. That is the failure this element exists
to make visible: a QC tester reading *"monthly ... 2025"* has found a binding error,
and an element assembled from two independent fields could never show them disagreeing.

**The home country is never named.** National scope is the *absence* of a country
(AD-5), so it renders through ``scope.national`` -- a phrase the catalogue owns in both
languages -- and the country whose data this is appears as a literal nowhere in the
engine. A named set states the country ids the spec actually bound, because *"what was
compared with what"* is the question the element answers.

The role is not an argument. ``scope_element`` returns a ``Placed`` whose role is
``Role.SCOPE``, so *"an answer carries an element of role scope"* is a property of the
constructor rather than a habit of its callers -- and the lens mapping in ``rules/``
then shows it in both lenses (FR-59b).
"""

from __future__ import annotations

from enum import StrEnum

from askai.assemble.elements import derived
from askai.assemble.provenance import Provenance
from askai.assemble.roles import Placed, Role
from askai.domain.period import Grain
from askai.domain.scope import CountryScope, DeclaredBenchmarks, Named, National
from askai.messages import Catalogue, CatalogueError, Lang, render, render_period

__all__ = ["ScopeMessage", "scope_element", "scope_statement"]


class ScopeMessage(StrEnum):
    """The message ids this module renders. Ids, not wording -- the wording is data."""

    STATEMENT = "scope.statement"
    """The three fragments, in the order and with the punctuation the language uses."""

    NATIONAL = "scope.national"
    BENCHMARKS = "scope.benchmarks"
    NAMED = "scope.named"
    LIST_SEPARATOR = "scope.list_separator"

    GRAIN_MONTHLY = "grain.monthly"
    GRAIN_QUARTERLY = "grain.quarterly"
    GRAIN_YEARLY = "grain.yearly"


def scope_statement(
    catalogue: Catalogue, lang: Lang, provenance: Provenance, country_scope: CountryScope
) -> str:
    """*"monthly, National, April 2026"* -- in *lang*, from the catalogue.

    The grain and the period come from the provenance, so they are the ones the figure
    was actually read at; the country scope comes from the bound spec, because a single
    row's country cannot say whether it was one of several compared.
    """
    return render(
        catalogue,
        lang,
        ScopeMessage.STATEMENT.value,
        grain=_grain_words(catalogue, lang, provenance.grain),
        scope=_country_words(catalogue, lang, country_scope),
        period=render_period(catalogue, lang, provenance.period),
    )


def scope_element(
    catalogue: Catalogue, lang: Lang, provenance: Provenance, country_scope: CountryScope
) -> Placed:
    """The ``scope`` element, placed in its role and sourced to *provenance*.

    Class ``derived``: the statement is computed here from the bound spec and the
    published row's own period, with both stated in the content -- which is exactly what
    ``derived`` means, and is why a scope element is not ``measured``. It carries the
    same ``source_ref`` as the figure it describes, so a statement that survived into an
    answer whose figure was refused is impossible: the two are admitted or refused
    together.
    """
    return Placed(
        element=derived(scope_statement(catalogue, lang, provenance, country_scope), provenance),
        role=Role.SCOPE,
    )


def _grain_words(catalogue: Catalogue, lang: Lang, grain: Grain) -> str:
    """*grain*, written as the language writes it.

    Exhaustive on the enum with no fallback: a grain the engine reads is a grain it must
    be able to say, and a default here would put one grain's word on another's answer.
    """
    match grain:
        case Grain.MONTHLY:
            message = ScopeMessage.GRAIN_MONTHLY
        case Grain.QUARTERLY:
            message = ScopeMessage.GRAIN_QUARTERLY
        case Grain.YEARLY:
            message = ScopeMessage.GRAIN_YEARLY
        case _:
            raise CatalogueError(
                f"{grain!r} has no word in the catalogue; a grain the engine answers at "
                "is a grain the answer has to be able to name"
            )
    return render(catalogue, lang, message.value)


def _country_words(catalogue: Catalogue, lang: Lang, country_scope: CountryScope) -> str:
    """The country scope, said rather than serialised.

    Exhaustive over the closed ``CountryScope`` set. A new member added without a phrase
    here fails loudly, which is the alternative to it quietly rendering as the national
    case -- the shape AD-5 exists to prevent, arriving through an omission.
    """
    match country_scope:
        case National():
            return render(catalogue, lang, ScopeMessage.NATIONAL.value)
        case DeclaredBenchmarks():
            return render(catalogue, lang, ScopeMessage.BENCHMARKS.value)
        case Named(countries=countries):
            separator = render(catalogue, lang, ScopeMessage.LIST_SEPARATOR.value)
            return render(
                catalogue,
                lang,
                ScopeMessage.NAMED.value,
                countries=separator.join(sorted(countries)),
            )
        case _:
            raise CatalogueError(
                f"{type(country_scope).__name__} is not a country scope the answer can "
                "state; a scope the engine binds is a scope it has to be able to say"
            )
