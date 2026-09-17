"""``CommentaryPort`` -- the analyst note bound to one datapoint, fetched by exact key.

Purity: declaration only.

An analyst note carries an indicator, a grain, a period and a country. It is bound to a
figure, which is what makes it class ``attributed`` and not class ``article``; the
separation is ``domain/element.py``'s, and this port is the fetch that respects it. There
is one method, it takes the whole ``(detail, period, country)`` key, and there is no
method here that returns "the nearest", "the best" or "the most relevant" note -- finding
*which* passage is relevant is a semantic question asked of a different file (Epic 6).
This one only answers "what did the analyst write about **this** row".

**A note is never a figure.** Nothing on this port returns a number, and AD-3 is
untouched by it: the value in an answer still comes from ``execute/`` and still names the
datapoint it was read from. The commentary rides beside the figure with its own
provenance and its own class, so a reader can see which of the two is measured.

**The national marker is the absence of a country, spelled ``None``** -- the same shape
as ``DatapointsPort``, because the two keys are the same key and a scope spelled
differently on one of them would fetch commentary for a different question.

**Absence is the normal case and is not a failure.** 1,031 of 8,127 datapoints carry any
commentary at all and 652 a substantive English summary, so ``None`` comes back from nine
calls in ten. That is why it is ``None`` rather than an exception: a miss here is the
published state of the data, not the store failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from askai.domain.period import Period
from askai.messages.lang import Lang

__all__ = ["Commentary", "CommentaryPort", "CommentaryUnavailable"]


class CommentaryUnavailable(RuntimeError):
    """The read model could not answer -- the port's own typed failure.

    A failure, never an absence, and the distinction is the whole reason it is declared:
    "no commentary is published for this row" is the common, correct answer and comes
    back as ``None``. This is the store not working, and it is typed so the layer above
    catches one named thing rather than a broad ``Exception`` (AD-15).
    """


@dataclass(frozen=True, slots=True)
class Commentary:
    """What an analyst wrote about one datapoint, as the read model holds it.

    The prose is the text the analyst wrote, decoded once at ingest -- never a summary
    of it. An engine that paraphrased an approved statement would be publishing an
    unapproved one under an approved one's provenance.

    Every column is optional because the export publishes them that way, and the key
    fields are not: a note that could not name the row it explains would be an
    ``article``, which is a different class with a different rule.
    """

    detail_id: str
    period: Period
    #: ``None`` is the national marker, and the only way to say "national" here.
    country_id: str | None
    #: The published row this note explains -- what makes the quote traceable.
    source_datapoint_id: str
    summary: tuple[str | None, str | None] = (None, None)
    detailed: tuple[str | None, str | None] = (None, None)

    def _in(self, pair: tuple[str | None, str | None], lang: Lang) -> str | None:
        return pair[0] if lang is Lang.EN else pair[1]

    def quotable(self, lang: Lang) -> str | None:
        """The passage to quote in *lang*, or ``None`` when this note publishes none.

        The summary, then the detailed analysis: the summary is what an analyst wrote to
        be read beside the figure, and the detailed analysis is what they wrote to be
        read instead of it. Falling back the other way would put several paragraphs
        where one sentence was published.

        **No cross-language fallback.** An Arabic answer carrying an English passage is
        finding 121's failure with a source_ref attached -- the reader asked in Arabic
        and would be shown text they may not read, sourced as though it were approved
        for them. Where the note publishes nothing in the asked language, the answer
        carries no commentary element, which is the ordinary case anyway.
        """
        return self._in(self.summary, lang) or self._in(self.detailed, lang)


class CommentaryPort(Protocol):
    """The analyst notes as ``narrate/`` sees them: one, by the datapoint's exact key."""

    def note(
        self, detail_id: str, period: Period, country_id: str | None
    ) -> Commentary | None:
        """The note on this exact key, or ``None`` when none is published.

        ``None`` never means "near miss" or "try an adjacent period": nothing here looks
        for one. A note explains the row it was written about, and a note fetched for a
        neighbouring period would be attributed to a figure the analyst was not
        discussing.
        """
        ...
