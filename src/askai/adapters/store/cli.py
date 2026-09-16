"""``python -m askai.adapters.store`` -- the preflight command (Story 1.7).

Purity: writes to the streams it is handed; the checks themselves live in ``preflight``.

The AC asks for the check to be *"invokable as a standalone command **and** run as a
startup precondition"*. Both call the same function, for the same reason ``rules/cli.py``
loads through the real ``load_rules()``: an operator who has run this command has proved
what startup would prove, rather than something adjacent to it.

The command prints the resolved absolute paths first and every check afterwards,
including the ones that passed, and exits non-zero if any failed. It reads the directory
from ``ASKAI_DATABASE_DIR`` through ``config/``'s typed settings -- there is no
``os.getenv`` here, which is the AC's last clause and a house rule besides.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from askai.adapters.store.database import SCHEMA_VERSION, SchemaError
from askai.adapters.store.preflight import MINIMUM_FREE_BYTES, preflight
from askai.adapters.store.provision import TABLE_OWNERS, provision
from askai.config.database import ConfigError, DatabasePaths

__all__ = ["main"]

_USAGE = (
    "usage: python -m askai.adapters.store [preflight|provision] [DIRECTORY]\n"
    "\n"
    "preflight  (the default) Checks that the database directory can hold the estate:\n"
    "           that it exists and is writable, has room, supports WAL and its sidecar\n"
    "           files, lets a reader run while a writer holds a lock, lets a file be\n"
    "           replaced under an open reader, and keeps a committed row across a\n"
    "           reopen.\n"
    "\n"
    "provision  Creates the three databases and their tables at the declared schema\n"
    "           version. Repeatable: an estate already at this version is left alone.\n"
    "           Run this once before the first refresh. The refresh opens the databases\n"
    "           and will not create them, because a schema appearing as a side effect of\n"
    "           ingest is how two environments come to disagree about what shape they\n"
    "           are in -- and that disagreement surfaces as a wrong answer rather than\n"
    "           as a missing file.\n"
    "\n"
    "With no DIRECTORY, reads ASKAI_DATABASE_DIR.\n"
)

#: The verbs, so a bare first argument is still read as a directory.
_COMMANDS = ("preflight", "provision")


def main(
    argv: Sequence[str] | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Run the preflight checks. 0 when every check passed, 1 when one did not, 2 on
    a configuration problem that stopped the checks being run at all.

    Three exit codes rather than two: "this machine is not fit" and "you have not told
    me which directory to look at" are different problems for whoever is reading the
    output, and a script that retries should retry only one of them.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    stream = sys.stdout if out is None else out
    errors = sys.stderr if err is None else err

    if any(argument in {"-h", "--help"} for argument in arguments):
        print(_USAGE, file=stream)
        return 0

    command = "preflight"
    if arguments and arguments[0] in _COMMANDS:
        command = arguments.pop(0)
    if len(arguments) > 1:
        print(_USAGE, file=errors)
        return 2

    try:
        paths = (
            DatabasePaths.beneath(Path(arguments[0]))
            if arguments
            else DatabasePaths.from_env()
        )
    except ConfigError as error:
        print(f"configuration: {error}", file=errors)
        return 2

    if command == "provision":
        return _provision(paths, stream, errors)

    report = preflight(paths, minimum_free_bytes=MINIMUM_FREE_BYTES)
    print(report.render(), file=stream)
    return 0 if report.ok else 1


def _provision(paths: DatabasePaths, stream: TextIO, errors: TextIO) -> int:
    """Create the estate, and say what it created.

    Separate from the refresh on purpose. The refresh opens the databases and refuses to
    create them, because a schema that appears as a side effect of ingest is how one
    environment quietly ends up a version behind another -- and the failure then shows up
    as a wrong answer rather than as a missing file.
    """
    paths.read_model.parent.mkdir(parents=True, exist_ok=True)
    try:
        with provision(paths) as databases:
            print(f"provisioned at schema version {SCHEMA_VERSION}", file=stream)
            for name, path in (
                ("read model", paths.read_model),
                ("record store", paths.record_store),
                ("semantic index", paths.semantic_index),
            ):
                print(f"  {name:15}{path}", file=stream)
            tables = sorted(TABLE_OWNERS)
            print(file=stream)
            print(f"{len(tables)} tables, each with one owning module:", file=stream)
            for table in tables:
                print(f"  {table:20}{TABLE_OWNERS[table]}", file=stream)
            del databases
    except (SchemaError, OSError) as error:
        print(f"provision: {error}", file=errors)
        return 1
    return 0
