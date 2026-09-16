"""The three stages, run in order. The binder's one door into resolution.

Purity: pure; calls ``CandidatePort`` for candidates and nothing else.

One function, and the order of the four lines inside it is AD-25. It is a module of its
own rather than a method on something because the *order* is the architecture: generate,
then discriminate, then decide, with no path that skips the middle one and no path that
lets stage 3 see stage 1's ranking. A caller that could reach ``decide`` with raw
candidates would have collapsed the ladder into the single scoring pass AD-25 forbids, and
the way to make that unavailable is to have one entry point that does all three.

**NFR-5 is a property of what this imports.** Nothing here, and nothing in the three
stages, imports a model client or a model port. The ladder produces a decision or a
disambiguation with no model reachable from it at all, so *"stages 1 and 2 still run when
the model is unavailable"* is not a fallback that has to be tested by taking a model away
-- there is nothing to take away. Story 2.6's tie-break is reached from *outside* this
function, with the disambiguation it returns as its input and its closed candidate list.
"""

from __future__ import annotations

from askai.compile.resolve.decide import Resolution, decide
from askai.compile.resolve.discriminate import QuestionSignals, discriminate
from askai.compile.resolve.generate import generate, subject_of
from askai.messages.lang import Lang
from askai.ports.resolution import CandidatePort

__all__ = ["resolve"]


def resolve(
    question: str,
    candidates: CandidatePort,
    asked: QuestionSignals | None = None,
    *,
    lang: Lang | None = None,
    limit: int | None = None,
) -> Resolution:
    """Resolve *question* to one detail, a named disambiguation, or a stated refusal.

    *asked* carries what the other binders have already extracted -- the named grain, the
    periods a range requires, the countries the reader named. It is an argument rather
    than something re-parsed here because AD-25 says stage 2 uses *"structural signals the
    compiler has already extracted"*, and a second reading of the question would be a
    second parser free to disagree with the first about what the reader said.

    ``None`` means the caller extracted nothing, which is a legitimate state -- a question
    naming no period, no grain and no country -- and leaves every weighted signal silent
    rather than guessing.
    """
    subject = subject_of(question)
    signals = QuestionSignals() if asked is None else asked
    # The subject is attached here rather than by the caller, so that the text stage 2
    # reads is always the text stage 1 scored. Two spellings of the subject is how the
    # gate and the overlap signal come to disagree about what the question was.
    signals = QuestionSignals(
        grain=signals.grain,
        window=signals.window,
        countries=signals.countries,
        subject=subject,
    )
    found = generate(subject, candidates, lang=lang, limit=limit)
    return decide(discriminate(found, signals))
