"""The base CMS layer, as names and existence only. It has no table and never will.

Purity: IO.

342 of the CMS's 531 indicators were never approved, and 281 of those carry a real
English name -- *"Classified Hotels (%)"*, *"The Rate of Volunteer Work"*. A reader will
ask about one. Answering *"this exists in the CMS but is not approved for publication"*
is a better refusal than *"I don't know about that"*, because it separates an editorial
gap from a failure of understanding (DATA-CONTRACT §1.4).

That is the whole of what the base layer is for here. It is loaded into memory as
:class:`~askai.ports.unpublished_catalogue.UnpublishedName` values -- two name fields
and nothing else -- and written to no table, so there is no row for a published query to
join to and no unapproved figure, period or definition anywhere in the read model.

Names are matched under the domain's single fold, so a reader's spelling meets a stored
one exactly as it does on the published side; a second fold here is the defect that
package exists to prevent.

:func:`existence_probe` is how Story 2.8 reaches this from a composer, and its return
type is the design: ``str -> bool | None``. A composer that held the port could ask it
for :meth:`UnpublishedCatalog.names`, and the hand after that would put one of those
names in a sentence; a composer that holds the probe can ask one question and receive
one bit. ``None`` is the third state -- *the catalogue could not be read* -- and it is
produced here, at the adapter boundary where AD-15 allows a foreign failure to be
converted into a value rather than a stack trace.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from askai.adapters.readmodel.export import CmsExport, Row
from askai.domain.normalise import normalise
from askai.domain.text import is_published_text
from askai.ports.unpublished_catalogue import UnpublishedCatalogPort, UnpublishedName
from askai.rules import RuleSet, rules

__all__ = ["MINIMUM_WORDS_RULE", "UnpublishedCatalog", "existence_probe"]

#: How many folded words an unapproved name must carry to be recognised inside a longer
#: question. A reader-affecting threshold, so it is a rule rather than a literal.
MINIMUM_WORDS_RULE = "R-UNAPPROVED-NAME-IS-RECOGNISED-IN-FULL"
_MINIMUM_WORDS_KEY = "minimum_words"


def _cell(row: Row, column: str) -> str:
    return row.get(column, "").strip()


@dataclass(frozen=True, slots=True)
class UnpublishedCatalog:
    """A read-only ``UnpublishedCatalogPort`` over the export, held in memory.

    Built once and frozen. There is no method here that writes, and no constructor that
    takes a connection, so this cannot become the back door through which the base layer
    reaches a database file.
    """

    entries: tuple[UnpublishedName, ...]
    by_name: Mapping[str, UnpublishedName]

    @classmethod
    def from_export(cls, export: CmsExport) -> UnpublishedCatalog:
        """Everything in the CMS catalogue that no published indicator maps back to.

        The published layer records the base id it came from, so "unapproved" is the
        complement of that set rather than a flag -- the base layer's own ``IsActive``
        and ``IsDeleted`` are ``True`` and ``False`` on all 531 rows and carry no signal.
        """
        published = {
            _cell(row, "SourceIndicatorId").casefold() for row in export.published_indicators()
        }
        entries: list[UnpublishedName] = []
        for row in export.base_indicators():
            if _cell(row, "Id").casefold() in published:
                continue
            name_en, name_ar = _cell(row, "NameEN"), _cell(row, "NameAR")
            # 61 base rows carry a blank English name. An entry with no name in either
            # language cannot be recognised or offered, so it is not an entry.
            if not is_published_text(name_en) and not is_published_text(name_ar):
                continue
            entries.append(UnpublishedName(name_en=name_en, name_ar=name_ar))

        ordered = tuple(sorted(entries, key=lambda entry: (entry.name_en, entry.name_ar)))
        index: dict[str, UnpublishedName] = {}
        for entry in ordered:
            for spelling in (entry.name_en, entry.name_ar):
                folded = normalise(spelling)
                if folded:
                    index.setdefault(folded, entry)
        return cls(entries=ordered, by_name=index)

    def holds(self, name: str) -> bool:
        """Does the unapproved catalogue carry *name*, in either language?"""
        return normalise(name) in self.by_name

    def names(self) -> Sequence[UnpublishedName]:
        """Every unapproved entry that carries a name, ordered by its English spelling."""
        return self.entries


def _minimum_words(rule_set: RuleSet) -> int:
    value = rule_set.value(MINIMUM_WORDS_RULE, _MINIMUM_WORDS_KEY)
    if not isinstance(value, int):
        raise TypeError(
            f"{MINIMUM_WORDS_RULE}.{_MINIMUM_WORDS_KEY} is {type(value).__name__}; the "
            "threshold a name is recognised by is a whole number of words"
        )
    return value


def _mentions(text: str, entries: Sequence[UnpublishedName], minimum_words: int) -> bool:
    """Does *text* contain the whole of an unapproved name, under the single fold?

    A reader asks *"what is the rate of volunteer work here?"*, not *"The Rate of
    Volunteer Work"*, so exact equality would recognise almost none of the 281 named
    unapproved indicators. Containment is bounded on both sides by a space in the folded
    form -- ``normalise`` collapses every separator to one -- so a name matches on whole
    words and never inside one.

    The answer is a boolean over the whole catalogue, so it does not depend on the order
    the entries are held in and there is no tie to break: two names matching is the same
    *yes* as one, and which of them matched is exactly the thing that must not leave.
    Names shorter than *minimum_words* words are skipped, because a single generic word
    is a coincidence rather than a reader naming an indicator.
    """
    folded = f" {normalise(text)} "
    for entry in entries:
        for spelling in (entry.name_en, entry.name_ar):
            name = normalise(spelling)
            if len(name.split()) < minimum_words:
                continue
            if f" {name} " in folded:
                return True
    return False


def existence_probe(
    port: UnpublishedCatalogPort, rule_set: RuleSet | None = None
) -> Callable[[str], bool | None]:
    """Existence over *port*, as the three-state question a composer may ask.

    ``True`` the catalogue holds what the reader named, ``False`` it does not, ``None``
    it could not be read. The boolean is the entire crossing: nothing a composer holds
    afterwards can name, date, define or value an unapproved row.

    The broad handler is the one AD-15 permits and only here, at the boundary: the port
    is a protocol, an implementation of it may be reading anything, and a composer that
    has to catch a driver error is a pure layer that has stopped being pure. Every
    failure becomes ``None``, which the caller renders as the weaker refusal plus a typed
    degradation -- never as a leak, and never as a crash.
    """
    minimum_words = _minimum_words(rules() if rule_set is None else rule_set)

    def probe(named: str) -> bool | None:
        try:
            return port.holds(named) or _mentions(named, port.names(), minimum_words)
        except Exception:
            return None

    return probe
