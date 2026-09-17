"""The index half of a refresh: the same export, published as a new generation.

Purity: IO, never on the answer path.

A refresh that reloads the read model and leaves the index alone leaves AD-25's ladder
resolving against names the read model no longer holds — a paraphrase binding to a
detail that answers *absent*, which reads like a data problem and is not one. So the two
halves are one job, and this module is the second half.

**Order: the read model first, then the index.** The ingest is one transaction and is the
thing a reader's answer comes out of; the index only decides *which* indicator a
paraphrase meant. Publishing the index first would open a window in which a resolved
detail has no rows behind it, which is the worse of the two windows. The window that does
exist — a new read model with the previous generation still in force — is the state the
system was already in before every refresh, and it resolves to names that still exist.

**Failure is reported, never raised through the refresh.** The read model has already
been replaced by the time this runs, and that work is committed and correct. So a build
that fails is an outcome the report carries and the exit code reflects — the operator is
told the deployment is now serving an index older than its data — rather than an
exception that would make a successful ingest look like a failed one.
"""

from __future__ import annotations

from dataclasses import dataclass

from askai.adapters.index.location import configured_source, generations_dir
from askai.adapters.index.publication import Published, publish_generation
from askai.adapters.readmodel.export import CmsExport
from askai.config.database import DatabasePaths
from askai.ports.vectors import VectorSourcePort

__all__ = ["IndexRebuild", "rebuild_index"]


@dataclass(frozen=True, slots=True)
class IndexRebuild:
    """What the index half of a refresh did. Exactly one of the two fields is set."""

    published: Published | None = None
    failure: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.failure is None

    def summary(self) -> str:
        """One operator-facing line, whichever way it went."""
        if self.published is not None:
            return f"index  {self.published.summary()}"
        return (
            f"index  NOT rebuilt: {self.failure}. The read model is current and the "
            "index is not; resolution is against the previous generation until a "
            "`python -m askai.adapters.index build` succeeds."
        )


def rebuild_index(
    paths: DatabasePaths,
    export: CmsExport,
    source: VectorSourcePort | None = None,
) -> IndexRebuild:
    """Publish a generation over *export* for the estate at *paths*.

    *source* is injectable so a test states the vector source it means; ``None`` reads
    the deployment's, which is the embedding runtime where one is configured.
    """
    try:
        published = publish_generation(
            export,
            configured_source() if source is None else source,
            generations_dir(paths),
        )
    except (OSError, RuntimeError) as error:
        return IndexRebuild(failure=str(error))
    return IndexRebuild(published=published)
