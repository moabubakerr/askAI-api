"""The operation a question asks for, read from its verb.

Purity: pure; reads the phrase tables in ``rules/`` and nothing else.

Every other binder reads the question's nouns. This one reads its **verb**, and until it
existed there was none: ``R-BIND-DEFAULT-OPERATION`` bound every question in the system to
``value``, so *"What does inflation mean?"* compiled to the same spec as *"What is
inflation now?"* and was answered with a figure.

The structure is ``compile.periods``'s, deliberately, because the problem is the same one:
a bilingual reading that must come out identical in both languages. Arabic puts the
qualifier where English does not, so nothing here is written around word order -- a
question is folded once, read as spans, and the spans are matched against the tables in
``rules/data/operation-words.yaml``. Neither language is the one the code is shaped around.

**No model** (AD-22). Operation classification is one of the four bounded model
call-sites, and the seam is left for it -- the words are the *first* rung and a model rung
would sit below them, after them, deciding only what they did not. Nothing behind that
seam is implemented here, and the reason is a gate rather than a preference: NFR-1
requires identical compilation on every run, ``tests/corpus_runner.py`` compiles all 86
corpus entries twice and fails on any difference, and a model inside the binder is the one
thing that could make the same question compile two ways.

**"What is X" is the case the whole file is shaped by.** *"What is inflation"* asks what
the word means; *"What is inflation now"* asks for a number. The frame is identical and
the period word is the entire difference. So the frame is read here and the period is
**not** -- the frame rung is told whether the reader named one, by the binder, which got
it from ``compile.periods``. A second period reading in this module would be a second
parser, free to disagree with the first about what the reader said, which is exactly the
failure ``compile.periods``'s own docstring exists to prevent.
"""

from __future__ import annotations

from askai.compile.lexicon import (
    bare_subject_frames,
    multi_reading_is_a_series,
    operation_words,
    readings_for_latest,
)
from askai.compile.question import Question, Span
from askai.domain.spec import LastN, Operation, PeriodSpec, Range

__all__ = ["operation_named"]


def operation_named(
    question: Question,
    request: PeriodSpec | None,
    *,
    excluding: Span | None,
    period_is_the_readers: bool,
) -> Operation | None:
    """The operation the question named, or ``None`` when it named none.

    Three rungs, in this order, and the order is the design.

    **The words**, longest phrase first. A reader who wrote "compare", "highest" or
    "trend" has said which question they are asking, and that outranks everything else --
    including a period the same sentence names, because *"compare inflation in 2019 and
    2025"* is a comparison that happens to name periods rather than a value question that
    happens to say compare.

    **The bare-subject frame**, only when the reader named no period. This is the rung
    ``R-OP-BARE-SUBJECT-IS-A-DEFINITION`` exists for, and *period_is_the_readers* is how it
    is told -- a fact the period binder already established, passed in rather than
    re-derived.

    **A multi-reading request**, when ``R-OP-SERIES-FROM-A-MULTI-READING-REQUEST`` is on.
    It is off today, because ``execute/`` produces no series and binding one would turn a
    partial answer into a refusal; the rung is built so that turning it on is a clause.

    ``None`` is not a failure and not a default: it is "the reader named no operation",
    and the binder walks on to the history and then to the rule default with it.
    """
    found = question.names_one_of(operation_words(), excluding=excluding)
    if found is not None:
        return found[0]
    if not period_is_the_readers and question.names(
        bare_subject_frames(), excluding=excluding
    ) is not None:
        return Operation.DEFINITION
    return _series_from(request)


def _series_from(request: PeriodSpec | None) -> Operation | None:
    """A request for more than one reading, read as a series -- when the rule says so.

    "More than one" is measured against ``R-BIND-GRAIN-FROM-DECLARED-DEFAULT``'s
    ``readings`` rather than against a number written here: that clause is what "the
    latest, at this grain" means, so a request for exactly that many readings is the
    latest reading and not a run of them. *"Last year"* is a value; *"the last five
    years"* is a series.
    """
    if not multi_reading_is_a_series() or request is None:
        return None
    match request:
        case Range():
            return Operation.SERIES
        case LastN(n=how_many) if how_many > readings_for_latest():
            return Operation.SERIES
        case _:
            return None
