"""``python -m askai.refresh`` -- the command a scheduled job runs. Not a route.

Purity: IO, never on the answer path.

FR-108 and AD-21 put refresh out of band: a job or a command, never something a reader's
request can trigger. That is a structural claim, so the entry point is a command-line
program and there is no HTTP handler anywhere that calls :func:`askai.refresh.run.run_refresh`.

The exit code is the contract. Zero means the read model now holds the export; one means
it does not, and in that case it still holds whatever the last successful refresh left,
because the ingest is one transaction. A scheduler that only watches exit codes learns
the right thing; the report on stdout is for the person the scheduler pages.

Text here is operator-facing, not reader-facing: it is read by whoever runs the job, in
one language, and never reaches an answer. The bilingual message catalogue (AD-11) owns
what a reader sees, and nothing on this path is shown to one.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from askai.adapters.readmodel.export import CmsExport
from askai.adapters.store.provision import open_databases
from askai.config.database import ConfigError, DatabasePaths
from askai.refresh.rejections import counts_by_class
from askai.refresh.report import RefreshReport
from askai.refresh.run import RefreshFailed, run_refresh
from askai.refresh.state import state_path_for

__all__ = ["main"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m askai.refresh",
        description=(
            "Replace the read model's contents from a CMS export, and report what "
            "changed, what was refused and what is now being served."
        ),
    )
    parser.add_argument("export", type=Path, help="the export directory, holding cms/")
    parser.add_argument(
        "--database-dir",
        type=Path,
        default=None,
        help=(
            "where the three databases live; defaults to the configured directory. "
            "There is no fallback to the working directory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "survey the export and report what would be refused, without touching the "
            "read model or the recorded state."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one refresh. Returns 0 when the read model now holds *export*, 1 otherwise."""
    arguments = _parser().parse_args(argv)
    try:
        paths = (
            DatabasePaths.from_env()
            if arguments.database_dir is None
            else DatabasePaths.beneath(arguments.database_dir)
        )
    except ConfigError as error:
        print(f"refresh cannot start: {error}")
        return 1

    export = CmsExport.rooted(arguments.export)
    state_path = None if arguments.dry_run else state_path_for(paths)
    try:
        with open_databases(paths) as databases:
            report = run_refresh(databases.read_model, export, state_path)
    except RefreshFailed as error:
        print(f"refresh not attempted: {error}")
        return 1
    except OSError as error:
        print(f"refresh could not reach its databases: {error}")
        return 1

    _print(report)
    return 0 if report.succeeded else 1


def _print(report: RefreshReport) -> None:
    print(report.summary())
    for table, before, after in (
        (change.table, change.before, change.after) for change in report.changed
    ):
        print(f"  changed  {table}: {before} -> {after}")
    for rejection_class, total in counts_by_class(report.rejections).items():
        print(f"  refused  {rejection_class.value}: {total} rows")
    for rejection in report.rejections:
        if not rejection.count:
            continue
        print(f"  {rejection.rejection_class.value} x{rejection.count} ({rejection.source})")
        print(f"    {rejection.reason}")
        for example in rejection.examples:
            print(f"      {example.identifier}: {example.detail}")
        if rejection.examples_are_truncated:
            print(f"      ... and {rejection.count - len(rejection.examples)} more")
