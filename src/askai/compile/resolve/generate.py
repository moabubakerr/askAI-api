"""Stage 1 of AD-25: cast a wide net, with no model and no threshold.

Purity: pure; calls ``CandidatePort`` and nothing else.

Two jobs, and they are separate because they pull in opposite directions.

**Find the subject.** *"inflation over the last 5 years"* is a question about inflation.
The words *over*, *the*, *last*, *5* and *years* say **when**, and R-158 is explicit that
a period phrase changes when a question asks about and never what. Scored as one bag of
text they compete for salience with the subject, and the epic's own example is what
happens then: a workforce-nationalisation indicator ranking on the span words alone,
because the reader's *five* and *years* found a name carrying numbers and spans. So the
period
vocabulary comes out first -- from the binder's own reviewed lists, per R-158 and R-162,
never from a second copy -- and the interrogative framing comes out with it.

That is measured, not assumed. Over ``names-v1`` it moves recall@10 from 85.4% to 89.0%
overall and paraphrase recall@10 from 47.6% to 57.1%, while leaving exact, typo, partial
and ambiguous recall untouched. Recall@10 is the ceiling on everything stage 2 could
possibly get right, so raising it is the whole of this stage's job.

**Then refuse what is merely adjacent.** Generation is high-recall by design and will
happily return a candidate that shares one short run of characters with the question.
The gate is **structural rather than a score threshold**, and Story 2.13 is why: the
relevant and irrelevant score distributions overlap across most of their range, so no
number separates *"Obesity Rate"* from *"what is the unemployment rate"* -- both contain
*rate* and both score plausibly. A shared content run of at least four characters says
something a score cannot, which is that the two are talking about the same thing at all.

**The subject is never allowed to become empty.** A question made entirely of framing
words -- *"what is it?"* -- strips to nothing, and scoring nothing would return an
arbitrary slice of the collection ordered by nothing. The full question is used instead,
so the worst case is the behaviour before stripping rather than a candidate list with no
relationship to what was asked.

**What the gate does not do, and the measurement that says so.** It is not a defence
against a question this corpus cannot answer. Over the 22 negative cases of ``names-v1``,
8 still resolve to a confident answer, and every one of them is admitted by a coincidental
run inside a *definition*: *Commodity Price Index* for "what is the average temperature in
summer", because its definition contains "average"; a greenhouse-crops indicator for
"ما هي درجة الحرارة اليوم؟", because its definition discusses temperature.

Restricting the gate to **name** surfaces was tried and measured, and it is not the
trade it appears to be. It halves the confident answers on negatives (8 to 5 of 22) and
costs recall@10 3.6 points overall, 20 points on synonyms -- because a definition is
genuinely how a paraphrase reaches an indicator whose name shares none of its words. Worse,
it *raised* the number of negatives answered confidently from 8 to 10, by converting
disambiguations into bindings: with fewer candidates admitted, the survivors stopped tying.

So the gate pools both, and the defence against an unanswerable question is left where
AD-30 puts it. Story 2.13 already measured that no score threshold separates these
distributions, which is exactly why Story 2.7's six distinct refusals are their own work
rather than a number here. ``Candidate.name_surfaces`` is carried for that story to use.
"""

from __future__ import annotations

from dataclasses import dataclass

from askai.compile.resolve.tuning import (
    gate_stopwords,
    minimum_ngram,
    period_vocabulary,
    request_vocabulary,
    strip_bare_numbers,
    strip_period_vocabulary,
)
from askai.domain.normalise import normalise
from askai.messages.lang import Lang
from askai.ports.resolution import Candidate, CandidatePort

__all__ = ["Subject", "admits", "content_ngrams", "generate", "subject_of"]


@dataclass(frozen=True, slots=True)
class Subject:
    """What a question is asking *about*, with the words that framed it removed.

    Both forms are kept. ``text`` is what stage 1 scores and what the gate compares; the
    reader's ``asked`` question is kept beside it because stage 2 reads the *rest* of the
    question -- a named sector, a named country, a word naming a unit shape -- and several
    of those words are ones this stage deliberately did not remove.
    """

    asked: str
    text: str

    #: The whole question, folded once by the engine's single ``normalise()``. Stage 2
    #: reads *this* rather than ``text``: a named sector, a country and a word naming a
    #: unit shape are all things stage 1 deliberately did not strip, and several of them
    #: -- ``rate``, ``number``, ``total`` -- sit inside published surfaces too.
    asked_folded: str = ""

    #: ``True`` when stripping removed everything and the full question was used instead.
    #: Carried rather than hidden so that a caller can tell a question with a subject from
    #: one that turned out to be entirely framing.
    was_all_framing: bool = False

    @property
    def words(self) -> tuple[str, ...]:
        return tuple(self.text.split())


def subject_of(question: str) -> Subject:
    """*question* with its period and request vocabulary removed (R-158, R-159, R-162).

    Folded once by the engine's single ``normalise()`` (AD-26) -- the same fold the index
    build used -- and then filtered. Multi-word period phrases are removed as phrases:
    *"most recent"* leaves nothing behind rather than leaving *"most"* to be scored.
    """
    folded = normalise(question)
    words = folded.split()
    if not words:
        return Subject(
            asked=question, text=folded, asked_folded=folded, was_all_framing=True
        )

    removable = set(request_vocabulary())
    if strip_period_vocabulary():
        removable |= set(period_vocabulary())
    kept = _without(words, removable)
    if strip_bare_numbers():
        kept = [word for word in kept if not word.isdigit()]

    text = " ".join(kept)
    if not text:
        # Entirely framing. Scoring an empty string returns an arbitrary slice of the
        # collection ordered by nothing, so the question as asked is the honest fallback.
        return Subject(
            asked=question, text=folded, asked_folded=folded, was_all_framing=True
        )
    return Subject(asked=question, text=text, asked_folded=folded)


def _without(words: list[str], removable: set[str]) -> list[str]:
    """*words* with every run matching a removable phrase taken out, longest run first.

    A phrase is matched as a run of adjacent words rather than word by word, because the
    reviewed vocabulary contains phrases -- *"most recent"*, *"at the moment"*,
    *"في الوقت الحالي"* -- and removing their words individually would leave the ones that
    are not themselves period words behind.
    """
    longest = max((len(phrase.split()) for phrase in removable), default=1)
    kept: list[str] = []
    index = 0
    while index < len(words):
        taken = 0
        # Longest run first: "most recent" must be preferred over "recent" alone, or the
        # phrase would be half-removed and "most" left to compete for salience.
        for length in range(min(longest, len(words) - index), 0, -1):
            if " ".join(words[index : index + length]) in removable:
                taken = length
                break
        if taken:
            index += taken
            continue
        kept.append(words[index])
        index += 1
    return kept


def content_ngrams(text: str, size: int) -> frozenset[str]:
    """Every character run of *size* in *text*'s content words.

    Two things are excluded, for two different reasons.

    **Runs spanning a space**, because a run across a word boundary is an artefact of word
    order rather than shared content: *"gdp real"* and *"real gdp"* are the same subject
    and would share no space-crossing run, while *"p re"* would match any two words
    beginning that way.

    **Generic measure nouns** (``gate_stopwords``), because they are what two unrelated
    indicators share. *"Obesity Rate"* and *"what is the unemployment rate"* share `rate`,
    which is itself exactly the reviewed run length, so without this the epic's own
    counter-example is admitted. These words are removed *here only* -- they stay in the
    text stage 1 scores, where they are the reader's own name for the thing.
    """
    ignored = gate_stopwords()
    runs: set[str] = set()
    for word in text.split():
        if word in ignored:
            continue
        for start in range(len(word) - size + 1):
            runs.add(word[start : start + size])
    return frozenset(runs)


def admits(subject: Subject, candidate: Candidate) -> bool:
    """Does *candidate* share a content run of the reviewed length with *subject*?

    The structural gate of Story 2.3. A candidate whose surfaces are all shorter than the
    reviewed run length is admitted rather than refused: a two-character published name
    cannot share a four-character run with anything, and refusing it would make the gate
    an unreachability rule for short names rather than a relevance test.
    """
    size = minimum_ngram()
    asked = content_ngrams(subject.text, size)
    if not asked:
        # The subject is shorter than one run. Nothing can share a run with it, so the
        # gate has nothing to say and admits rather than refusing everything.
        return True
    # Names **and** definitions, and the choice was measured both ways -- see this
    # module's docstring for the numbers and for what they say about whose job this is.
    for surface in candidate.surfaces:
        runs = content_ngrams(surface, size)
        if not runs:
            return True
        if runs & asked:
            return True
    return False


def generate(
    subject: Subject,
    candidates: CandidatePort,
    *,
    lang: Lang | None = None,
    limit: int | None = None,
) -> tuple[Candidate, ...]:
    """The candidates *subject* reaches, gated structurally, best first.

    Calls no model (AD-25 stage 1) and applies no score threshold: the only thing removed
    here is a candidate that shares no content with the question, and what survives is
    handed to stage 2 to be told apart on the rest of the question.
    """
    return tuple(
        candidate
        for candidate in candidates.candidates(subject.text, lang=lang, limit=limit)
        if admits(subject, candidate)
    )
