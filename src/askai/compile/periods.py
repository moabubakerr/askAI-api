"""Period expressions, in both languages, read as one ``PeriodSpec``.

Purity: pure; reads the phrase tables in ``rules/`` and nothing else.

FR-7 asks for four shapes of period expression and asks for them identically in English
and Arabic: the **absolute** form a reader writes (``2025``, ``2026-04``, ``Q4-2025``,
``الربع الرابع 2025``), the **relative** form (*"over the last 5 years"*, *"lately"*,
*"العام الماضي"*), a **span** (*"from 2019 to 2025"*, *"من 2021 إلى 2025"*) and an
**open** span (*"since 2019"*).

There is one parser for all of them and for both languages, and it is this module. That
is the whole design decision: Arabic puts a qualifier after the noun where English puts
it before, so a parser written around English word order needs a second parser for
Arabic -- and a second parser is how the two languages come to resolve the same question
differently. Instead a period expression is read as the *set of parts* it is made of --
a backward-pointing word, a count, an interval noun, a year, a month or quarter name --
and the parts are matched against the bilingual tables in ``rules/``. Neither language is
the one the code is shaped around.

Three boundaries this module does not cross:

**It never reads a clock and never reads the data.** ``today`` arrives as an argument,
so *"since 2019"* compiles to the same span on every run of the same day and to a
different one tomorrow (AD-17); and a relative expression resolves to ``LastN``, which
is a *request* that ``execute/`` anchors on the published data (AD-1). Compile does not
get to decide which period is the newest one.

**It resolves to published period forms only.** ``Period`` is the single authority on
what a published period is, so *"Q4-2025"* -- a reader's spelling, not a published one --
is read here and handed to ``Period`` as ``2025-Q4``. Nothing downstream ever sees the
reader's spelling.

**It invents nothing.** A month or a quarter named with no year names an *interval*, not
a period: picking the year would be compile choosing a reading the reader never asked
for. Two periods with a comparison word between them stay two periods, because a
comparison of two readings (FR-23) and a run of readings across them (FR-16) are
different questions and the engine is not entitled to pick.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from askai.compile.binding import UnboundReason
from askai.compile.lexicon import (
    comparison_words,
    count_words,
    month_numbers,
    open_range_ends_at_today,
    period_nouns,
    period_prefixes,
    quarter_numbers,
    range_from_words,
    range_to_words,
    readings_for_latest,
    relative_back_words,
)
from askai.compile.question import Question, Span
from askai.domain.normalise import normalise
from askai.domain.period import Grain, Period, PeriodFormatError
from askai.domain.spec import Exact, LastN, Latest, PeriodSpec, Range

__all__ = ["PeriodRefusal", "grain_of", "implied_grain", "period_named"]


@dataclass(frozen=True, slots=True)
class PeriodRefusal:
    """The reader named periods the engine will not turn into one request.

    Carries the closed cause and its particulars rather than an ``Unbound``: the binder
    owns the ladder and the field states, and this module owns the reading.
    """

    reason: UnboundReason
    particulars: str


def period_named(
    question: Question, today: date, *, excluding: Span | None
) -> PeriodSpec | PeriodRefusal | None:
    """What the question named as its period, or ``None`` when it named none.

    The order is the order of specificity, not of convenience: periods the reader spelt
    out are read first, and a relative expression is consulted only when no period was
    named -- "the first quarter of 2026" is that quarter, whatever else the sentence says.
    """
    named = _periods_named(question, excluding=excluding)
    first, *rest = named or (None,)
    if first is None:
        return _relative(question, excluding=excluding)
    if rest:
        return _span(question, named)
    opened = _open_ended(question, first, today)
    return Exact(first) if opened is None else opened


def grain_of(request: PeriodSpec) -> Grain | None:
    """The interval a period request is at, or ``None`` when it names none.

    A period expression that implies an interval **counts as naming a grain** (FR-5), so
    this is what the binder checks against the detail's published grains (FR-6).
    Exhaustive: a ``PeriodSpec`` member added later fails here rather than quietly
    implying no grain and so skipping that check.
    """
    match request:
        case Exact(period=period):
            return period.grain
        case Range(start=start):
            return start.grain
        case LastN(grain=grain):
            return grain
        case Latest():
            return None
        case _:
            raise TypeError(
                f"{type(request).__name__} is not a PeriodSpec member, or is one "
                "grain_of has not been told about; say what interval it is at before "
                "putting it on a spec"
            )


def implied_grain(question: Question, *, excluding: Span | None) -> Grain | None:
    """The interval a month name or quarter phrase implies when it names no period.

    *"What was inflation in April?"* names no year, so it names no period -- but it does
    say monthly, and FR-5 counts that as naming a grain. Reading it as the interval is
    what keeps the alternative out: inventing the year.
    """
    parts = _parts(question, excluding=excluding)
    return None if not parts else parts[0].grain


# ------------------------------------------------------------- the periods a reader spells


def _as_period(word: str) -> Period | None:
    """*word* as a published period, or ``None``. ``Period`` is the only authority.

    A word is offered to ``Period`` again without its leading conjunction when it carries
    one, because Arabic writes "and 2025" as a single word and the fold does not split a
    clitic off (AD-26). ``Period`` still decides; this only says which spellings are
    offered to it.
    """
    try:
        return Period(word)
    except PeriodFormatError:
        pass
    for prefix in sorted(period_prefixes()):
        if word.startswith(prefix):
            try:
                return Period(word[len(prefix) :])
            except PeriodFormatError:
                continue
    return None


def _spelled_out(question: Question) -> frozenset[Period]:
    """Every period the reader spelt as one word -- ``2025``, ``2026-04``, ``2025-Q1``.

    Read off the *raw* words, because the fold collapses punctuation and ``2026-04``
    folded is ``2026 04``. What this set is for is confirming that a year and the number
    beside it really were written as one period: two adjacent numbers otherwise are two
    numbers, and reading them as a month would invent a period out of a coincidence.
    """
    found: set[Period] = set()
    for word in question.raw_words:
        parsed = _as_period(word)
        if parsed is not None:
            found.add(parsed)
    return frozenset(found)


def _years(question: Question) -> tuple[tuple[int, Period], ...]:
    """The years the folded words carry, each with the word it sits at.

    Read off the folded words rather than the raw ones because that is where every
    spelling puts the year in reach -- ``Q4-2025`` is a raw word ``Period`` refuses, and
    folded it is two words, one of which is the year.

    Not deduplicated: *"from 2024-Q1 to 2024-Q4"* names one year twice and two periods,
    and a year collapsed to its first mention would lose the second quarter with it. The
    periods it resolves to are deduplicated instead, where duplication is real.
    """
    found: list[tuple[int, Period]] = []
    for index, word in enumerate(question.words):
        parsed = _as_period(word)
        if parsed is not None and parsed.grain is Grain.YEARLY:
            found.append((index, parsed))
    return tuple(found)


def _dated(
    question: Question, index: int, year: Period, spelled: frozenset[Period]
) -> Period | None:
    """The monthly period a year and the word after it spell, when they spell one.

    ``2026-04`` arrives folded as two words, and only the raw spelling says the reader
    wrote them as one period -- so the pair is accepted only when the whole period is in
    the set of periods actually spelt out. The quarterly spelling needs nothing here: a
    folded ``2025-Q4`` is a year beside the quarter phrase ``q4``, which is read as the
    part of a year it is.
    """
    following = index + 1
    if following >= len(question.words):
        return None
    candidate = _as_period(f"{year.value}-{question.words[following]}")
    return candidate if candidate in spelled else None


@dataclass(frozen=True, slots=True)
class _Part:
    """A month name or a quarter phrase: the part of a year the reader named."""

    span: Span
    grain: Grain
    number: int

    def of(self, year: Period) -> Period:
        """This part of *year*, in the published spelling."""
        if self.grain is Grain.MONTHLY:
            return Period(f"{year.value}-{self.number:02d}")
        return Period(f"{year.value}-Q{self.number}")


def _parts(question: Question, *, excluding: Span | None) -> tuple[_Part, ...]:
    """Every month name and quarter phrase the question carries, left to right.

    Spans are walked longest-first, so *"the first quarter"* is one part rather than a
    quarter phrase and a stray word, and a span overlapping one already taken is skipped
    so that nothing is counted twice.
    """
    months, quarters = month_numbers(), quarter_numbers()
    taken: list[Span] = []
    found: list[_Part] = []
    for span in question.spans():
        if span.overlaps(excluding) or any(span.overlaps(other) for other in taken):
            continue
        month = months.get(span.text)
        quarter = quarters.get(span.text)
        if month is not None:
            found.append(_Part(span=span, grain=Grain.MONTHLY, number=month))
        elif quarter is not None:
            found.append(_Part(span=span, grain=Grain.QUARTERLY, number=quarter))
        else:
            continue
        taken.append(span)
    return tuple(sorted(found, key=lambda part: part.span.start))


def _periods_named(question: Question, *, excluding: Span | None) -> tuple[Period, ...]:
    """The periods the question named outright, in the order it named them.

    A month or quarter named in words is a period only alongside a year: "April" on its
    own names no year, and picking one would be compile inventing a period.

    Every period is read from the year it belongs to, whatever spelling that year came
    in, so one span may be written two ways -- *"from April 2025 to 2026-04"* -- and
    still be one range.
    """
    spelled = _spelled_out(question)
    years = _years(question)
    if not years:
        return ()

    dated = {index: _dated(question, index, year, spelled) for index, year in years}
    open_years = tuple((index, year) for index, year in years if dated[index] is None)
    paired = _pair(open_years, _parts(question, excluding=excluding))

    found: list[Period] = []
    for index, year in years:
        part = paired.get(index)
        resolved = dated[index] or (year if part is None else part.of(year))
        if resolved not in found:
            found.append(resolved)
    return tuple(found)


def _pair(
    years: tuple[tuple[int, Period], ...], parts: tuple[_Part, ...]
) -> dict[int, _Part]:
    """Give each year the month or quarter name nearest to it, closest pair first.

    Closest-first rather than left-to-right: *"from 2019 to the first quarter of 2025"*
    would otherwise hand the quarter to 2019 merely for being mentioned earlier. Ties
    break on the order of the question, so the pairing is the same on every run (AD-17).
    """
    candidates = sorted(
        (_distance(index, part), position, offset)
        for position, (index, _) in enumerate(years)
        for offset, part in enumerate(parts)
    )
    paired: dict[int, _Part] = {}
    used: set[int] = set()
    for _, position, offset in candidates:
        index = years[position][0]
        if index in paired or offset in used:
            continue
        paired[index] = parts[offset]
        used.add(offset)
    return paired


def _distance(index: int, part: _Part) -> int:
    """How far a year sits from a month or quarter name, in words."""
    return min(abs(part.span.start - index), abs(part.span.stop - index))


# --------------------------------------------------------------------------- spans


def _span(question: Question, named: tuple[Period, ...]) -> Range | PeriodRefusal:
    """Two named periods as a span -- when the question says they are one (FR-7, FR-16).

    A span word ("from ... to", "من ... إلى") is what makes a range; a comparison word
    ("between ... and", "بين ... و", "compare") is what stops one, because that is a
    question about two readings rather than about the run between them (FR-23). Neither
    present, the reader named two periods and the engine says so rather than picking.
    """
    first, second, *rest = named
    spelt = ", ".join(str(period) for period in named)
    ambiguous = (
        bool(rest)
        or question.names(comparison_words()) is not None
        or question.names(range_to_words()) is None
        or first.grain is not second.grain
    )
    if ambiguous:
        return PeriodRefusal(UnboundReason.MORE_THAN_ONE_PERIOD_NAMED, spelt)
    if first.start > second.start:
        return PeriodRefusal(UnboundReason.PERIOD_RANGE_RUNS_BACKWARDS, spelt)
    return Range(start=first, end=second)


def _open_ended(question: Question, named: Period, today: date) -> Range | PeriodRefusal | None:
    """*"since 2019"* -- a span the reader opened and did not close.

    The end is the period containing ``today`` at the grain the reader's own start period
    names, which is ``R-BIND-OPEN-RANGE-ENDS-AT-TODAY``. The span may well run past the
    newest published reading; stating that is ``execute/``'s job (FR-17), and shortening
    it here would need the data compile cannot see.
    """
    if not open_range_ends_at_today() or not _opened(question, named):
        return None
    end = _containing(today, named.grain)
    if named.start > end.start:
        return PeriodRefusal(UnboundReason.PERIOD_RANGE_RUNS_BACKWARDS, f"{named}, {end}")
    return Range(start=named, end=end)


def _opened(question: Question, named: Period) -> bool:
    """Does a span word stand immediately before *named*?

    Adjacency, not presence: "from" and especially Arabic "من" are ordinary words --
    *"public debt as a percentage of GDP in 2021"* is written with one in Arabic and is
    not a span. Standing directly before the period is what makes it the span's opening.
    """
    opening = range_from_words()
    previous = ""
    for word in question.raw_words:
        if _as_period(word) == named and normalise(previous) in opening:
            return True
        previous = word
    return False


def _containing(today: date, interval: Grain) -> Period:
    """The period at *interval* that ``today`` falls in.

    The quarter is found by asking each published quarter whether it contains the day,
    rather than by dividing the month: the arithmetic would put a calendar constant in
    code, and ``Period`` already knows where every quarter starts and ends.
    """
    match interval:
        case Grain.YEARLY:
            return Period(f"{today.year:04d}")
        case Grain.MONTHLY:
            return Period(f"{today.year:04d}-{today.month:02d}")
        case Grain.QUARTERLY:
            for number in sorted(set(quarter_numbers().values())):
                candidate = Period(f"{today.year:04d}-Q{number}")
                if candidate.start <= today <= candidate.end:
                    return candidate
            raise ValueError(  # pragma: no cover -- the four quarters cover every day
                f"{today} falls in no quarter of {today.year}; the quarter table in "
                "R-BIND-QUARTER-WORDS names the quarters a year has"
            )


# ----------------------------------------------------------------- relative expressions


class _Kind(StrEnum):
    """The parts a relative period expression is made of."""

    BACK = "back"
    COUNT = "count"
    NOUN = "noun"


@dataclass(frozen=True, slots=True)
class _Element:
    """One part, and whatever it carries: a count carries a number, a noun an interval."""

    kind: _Kind
    number: int | None = None
    grain: Grain | None = None


def _element(phrase: str) -> _Element | None:
    """*phrase* as a part of a relative expression, or ``None`` if it is not one."""
    if phrase in relative_back_words():
        return _Element(kind=_Kind.BACK)
    counted = count_words().get(phrase)
    if counted is not None:
        return _Element(kind=_Kind.COUNT, number=counted)
    if phrase.isdecimal():
        return _Element(kind=_Kind.COUNT, number=int(phrase))
    for interval, nouns in period_nouns().items():
        if phrase in nouns:
            return _Element(kind=_Kind.NOUN, grain=interval)
    return None


def _elements(words: list[str]) -> tuple[_Element, ...] | None:
    """Every word of a candidate expression as a part, or ``None`` if one is not a part.

    Longest phrase first, so "اثني عشر" is the count twelve rather than two words neither
    of which is a count. A word that is not a part at all rejects the whole candidate:
    that is what stops "month on month" being read as a relative expression.
    """
    found: list[_Element] = []
    start = 0
    while start < len(words):
        for stop in range(len(words), start, -1):
            element = _element(" ".join(words[start:stop]))
            if element is not None:
                found.append(element)
                start = stop
                break
        else:
            return None
    return tuple(found)


def _relative(question: Question, *, excluding: Span | None) -> LastN | None:
    """*"over the last 5 years"*, *"السنوات الخمس الماضية"* -- the last *n* at an interval.

    The parts are matched as a set rather than as a word order, which is what makes the
    English and the Arabic one expression: exactly one interval noun, at least one
    backward-pointing word, and at most one count. No count means one period --
    ``R-BIND-GRAIN-FROM-DECLARED-DEFAULT``'s ``readings`` -- so *"last year"* and
    *"العام الماضي"* are the same request as "the latest yearly reading".
    """
    for span in question.spans():
        if span.overlaps(excluding):
            continue
        elements = _elements(span.text.split())
        if elements is None:
            continue
        nouns = [element for element in elements if element.kind is _Kind.NOUN]
        backs = [element for element in elements if element.kind is _Kind.BACK]
        counts = [element.number for element in elements if element.kind is _Kind.COUNT]
        if len(nouns) != 1 or not backs or len(counts) > 1:
            continue
        interval = nouns[0].grain
        how_many = readings_for_latest() if not counts else counts[0]
        if interval is None or how_many is None or how_many < 1:
            continue
        return LastN(n=how_many, grain=interval)
    return None
