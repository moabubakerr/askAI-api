"""``compile/resolve/`` -- AD-25's three stages, in the order the architecture fixes them.

Purity: pure; calls ``CandidatePort`` for candidates and nothing else.

Epic 1 resolved a detail by exact normalised-name lookup and refused everything else.
That rung stays and stays first -- it is the cheapest and the most reliable, measured at
96% recall@1 on the labelled set -- and this package is the ladder beneath it, for the
257 of 320 published names that are ambiguous and the readers who paraphrase.

The three stages are three modules because AD-25 forbids collapsing them into one scoring
pass, and a seam that exists only in a docstring is a seam that closes:

* :mod:`~askai.compile.resolve.generate` -- stage 1. Strip the words that say *when*,
  score what is left, admit on a structural gate. No model, high recall.
* :mod:`~askai.compile.resolve.discriminate` -- stage 2. Use the rest of the question
  against the candidates' published facts. Deterministic, before any model call.
* :mod:`~askai.compile.resolve.decide` -- stage 3. Bind one, name several, or refuse
  with a stated cause.

:mod:`~askai.compile.resolve.ladder` runs them in that order and is the only entry point
the binder uses.

**Why stage 2 exists at all, in one measurement.** Over ``names-v1``, where a wrong
candidate outranked the right one, that wrong candidate's median score was 0.831 against a
derived floor of 0.838, and its 95th percentile was identical to the relevant 95th
percentile. By score alone a wrong top answer is indistinguishable from a right one. No
threshold recovers that, which is why stage 2 is structural and why it may never re-rank
on stage 1's score.
"""

from __future__ import annotations

from askai.compile.resolve.coverage import PeriodWindow, window_for
from askai.compile.resolve.decide import (
    Disambiguation,
    Refusal,
    RefusalCause,
    Resolution,
    Resolved,
    decide,
)
from askai.compile.resolve.discriminate import (
    Discriminated,
    QuestionSignals,
    Scored,
    Signal,
    SignalName,
    Vetoed,
    discriminate,
)
from askai.compile.resolve.generate import Subject, generate, subject_of
from askai.compile.resolve.ladder import resolve

__all__ = [
    "Disambiguation",
    "Discriminated",
    "PeriodWindow",
    "QuestionSignals",
    "Refusal",
    "RefusalCause",
    "Resolution",
    "Resolved",
    "Scored",
    "Signal",
    "SignalName",
    "Subject",
    "Vetoed",
    "decide",
    "discriminate",
    "generate",
    "resolve",
    "subject_of",
    "window_for",
]
