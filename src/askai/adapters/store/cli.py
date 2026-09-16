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

from askai.adapters.store.preflight import MINIMUM_FREE_BYTES, preflight
from askai.config.database import ConfigError, DatabasePaths

__all__ = ["main"]

_USAGE = (
    "usage: python -m askai.adapters.store [DIRECTORY]\n"
    "\n"
    "Checks that the database directory can hold the estate: that it exists and is\n"
    "writable, has room, supports WAL and its sidecar files, lets a reader run while a\n"
    "writer holds a lock, lets a file be replaced under an open reader, and keeps a\n"
    "committed row across a reopen.\n"
    "\n"
    "With no DIRECTORY, reads ASKAI_DATABASE_DIR.\n"
)


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

    report = preflight(paths, minimum_free_bytes=MINIMUM_FREE_BYTES)
    print(report.render(), file=stream)
    return 0 if report.ok else 1
