"""Publishing a generation: build it, prove it loads, then retire what it superseded.

Purity: IO.

:mod:`askai.adapters.index.build` makes a generation and :mod:`askai.adapters.index.quality`
makes one to measure and throws it away. Neither *publishes* one, which is why AD-25's
ladder was built, tested and unreachable: no deployment had a generation to resolve
against. This module is the production build step, and it is three things in an order
that matters.

**Built, then loaded, then retired.** The new generation is loaded back before anything
is deleted, so a build that produced a file the loader refuses — a width that disagrees
with the source, a truncated embedding — leaves the previous generation in place and
serving. Retiring first would turn one bad build into an estate with no index at all.

**Retirement is an unlink of a superseded file, not a reference swap.**
:class:`askai.adapters.index.swap.SwappableIndex` is the in-*process* mechanism: it
rebinds one reference for a process that is holding a generation in memory. Refresh is
out of band (AD-21) and runs in a different process from the server, so there is no
reference here to rebind; what the two mechanisms share is the same rule, and it is kept
here too — the file in force is never the one deleted, because the one deleted was
listed before the new one existed.

**A generation is built from the export, not from the read model.** The same export the
refresh just loaded, in the same job, so the names the ladder resolves against and the
rows an answer is read out of describe one corpus. An index rebuilt from a different
export would resolve to details the read model no longer holds — a paraphrase binding to
an indicator that then answers *absent*, which reads like a data problem and is not one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from askai.adapters.index.build import build_generation
from askai.adapters.index.facts import detail_facts
from askai.adapters.index.generation import load_generation
from askai.adapters.index.location import published_generations
from askai.adapters.index.names import name_rows
from askai.adapters.readmodel.export import CmsExport
from askai.ports.index import Collection
from askai.ports.vectors import VectorSourcePort

__all__ = ["Published", "publish_generation"]


@dataclass(frozen=True, slots=True)
class Published:
    """What one publication did, measured from the file rather than from intent."""

    path: Path
    built_at: str
    source_identity: str
    names: int
    details: int
    retired: tuple[Path, ...]

    def summary(self) -> str:
        """One operator-facing line. Not reader-facing text, so not in the catalogue."""
        return (
            f"published {self.path.name}: {self.names} name surfaces and "
            f"{self.details} details, built by {self.source_identity} at {self.built_at}"
            f"; retired {len(self.retired)}"
        )


def publish_generation(
    export: CmsExport,
    source: VectorSourcePort,
    directory: Path,
    *,
    built_at: str | None = None,
) -> Published:
    """Build a generation over *export* into *directory* and make it the one in force.

    Raises rather than degrading: ``IndexBuildError`` from the build, ``IndexLoadError``
    from the verifying load, ``OSError`` from the filesystem. An index that is quietly
    missing rows answers plausibly from a corpus that is not the published one, and the
    caller — an operator, or the refresh job that pages one — is the right place to
    decide what a failure means.
    """
    superseded = published_generations(directory)
    rows = name_rows(export)
    facts = detail_facts(export)
    path = build_generation(
        directory,
        {Collection.NAMES: rows},
        source,
        built_at=built_at,
        facts=facts,
    )
    # Loaded before anything is retired, and against the same source it was built with:
    # every check the serving process will make at startup is made here instead, where
    # there is still a previous generation to fall back on.
    generation = load_generation(path, source)
    retired: list[Path] = []
    for old in superseded:
        if old == path:
            continue
        old.unlink(missing_ok=True)
        retired.append(old)
    return Published(
        path=path,
        built_at=generation.built_at,
        source_identity=generation.source_identity,
        names=generation.size(Collection.NAMES),
        details=len(facts),
        retired=tuple(retired),
    )
