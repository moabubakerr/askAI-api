"""FTS5 over the same ``names`` rows -- the lexical half of the hybrid, in one system.

Purity: IO.

Story 2.2 asks for exact names, codes and misspellings to be found lexically, and is
explicit about how: *"SQLite FTS5 over the same ``names`` table is fused with the cosine
score -- hybrid search with no second system."* Both halves of that sentence are enforced
here.

**Same rows.** The index holds one table of name rows and one full-text table built from
it, in the same generation file, written in the same transaction, published by the same
rename. There is no second store to keep in step, nothing to reindex separately, and no
state in which the lexical half describes a corpus the vector half does not.

**Same fold.** What is indexed is ``normalise(text)``, not the published spelling, and a
question is folded by the same call before it becomes a MATCH expression (AD-26). This is
where a lexical matcher usually drifts from its vector counterpart: FTS5's own
``remove_diacritics`` would fold Latin text and leave the hamza and teh-marbuta variation
the Arabic half turns on, so the tokeniser is never asked to do the folding. It only
splits.

**No second system.** ``sqlite3`` is already the estate's store; FTS5 is compiled into it.
Nothing here opens a socket, loads a model or holds a process.

A generation file is written once and thereafter read-only, so a query opens it
``mode=ro`` and closes it again. That keeps the search thread-safe without a shared
connection, and costs one open on a file the operating system has cached.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from askai.domain.normalise import normalise
from askai.ports.index import IndexRow

__all__ = [
    "NAMES_LEXICAL_TABLE",
    "create_names_lexical_table",
    "lexical_scores",
    "populate_names_lexical",
]

#: The full-text table over the ``names`` collection. Named for what it is rather than
#: with the ``vec_`` prefix, because it holds no vector: a reader of the file should not
#: have to open it to find out which half of the hybrid a table belongs to.
NAMES_LEXICAL_TABLE: Final = "fts_names"

#: ``unicode61`` splits on Unicode category, which is all this tokeniser is asked to do.
#: Diacritic removal is left off on purpose: the text it indexes has already been through
#: the engine's one fold, and a second, differently-specified fold here is exactly the
#: drift AD-26 exists to prevent.
_TOKENIZER: Final = "unicode61 remove_diacritics 0"

_QUOTE: Final = '"'


def create_names_lexical_table(connection: sqlite3.Connection) -> None:
    """Create the full-text table. Called once, by the index schema, per generation."""
    connection.execute(
        f"CREATE VIRTUAL TABLE {NAMES_LEXICAL_TABLE} USING fts5("
        # The row id is stored and not indexed: it is a GUID triple that no reader ever
        # searches for, and indexing it would let a question match a key.
        f"row_id UNINDEXED, folded, tokenize = '{_TOKENIZER}')"
    )


def populate_names_lexical(connection: sqlite3.Connection, rows: Sequence[IndexRow]) -> None:
    """Index *rows*' folded text for lexical match, alongside their vectors."""
    statement = "INSERT INTO " + NAMES_LEXICAL_TABLE + " (row_id, folded) VALUES (?, ?)"
    connection.executemany(statement, ((row.id, normalise(row.text)) for row in rows))


def match_expression(question: str) -> str | None:
    """*question* as an FTS5 MATCH expression, or ``None`` when it has no terms.

    Every token is quoted, so nothing a reader types is read as FTS5 syntax: a question
    containing ``AND``, ``NEAR`` or a bare ``*`` is a question, not a query language.
    Terms are OR-ed because this is a recall stage (AD-25 stage 1) -- requiring every
    token would drop the paraphrases the stage exists to catch.
    """
    terms = [
        _QUOTE + token.replace(_QUOTE, _QUOTE + _QUOTE) + _QUOTE
        for token in normalise(question).split(" ")
        if token
    ]
    return " OR ".join(terms) if terms else None


def lexical_scores(path: Path, question: str) -> Mapping[str, float]:
    """Row id to lexical score in ``(0, 1]``, for the rows *question* matches at all.

    BM25 is a corpus-relative quantity with no upper bound and a sign that depends on the
    library's convention (sqlite's is negative-is-better), so it is not a number that can
    be fused with a cosine as it stands. It is rescaled against the best score *this*
    question achieved, which makes the lexical half a within-query ranking signal -- which
    is what it is -- and keeps it in the same range as the cosine it is combined with.
    No threshold is applied: AD-30 requires a floor to be derived from a labelled set, and
    there is none yet.
    """
    expression = match_expression(question)
    if expression is None:
        return {}
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT row_id, bm25("
            + NAMES_LEXICAL_TABLE
            + ") FROM "
            + NAMES_LEXICAL_TABLE
            + " WHERE "
            + NAMES_LEXICAL_TABLE
            + " MATCH ?",
            (expression,),
        ).fetchall()
    except sqlite3.OperationalError:
        # The tokeniser found nothing indexable in a question that folded to something --
        # a string of symbols FTS5 discards. An empty lexical half is the honest result,
        # and the vector half still answers.
        return {}
    finally:
        connection.close()
    return _rescaled(rows)


def _rescaled(rows: Sequence[tuple[object, object]]) -> Mapping[str, float]:
    scored = {str(row_id): float(rank) for row_id, rank in rows if isinstance(rank, float)}
    best = min(scored.values(), default=0.0)
    if best >= 0.0:
        # Every match ranked at or above zero: nothing separates them, so the lexical
        # half contributes an order and not a magnitude.
        return dict.fromkeys(scored, 1.0)
    return {row_id: rank / best for row_id, rank in scored.items()}
