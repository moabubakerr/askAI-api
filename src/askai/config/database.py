"""Where the three database files live -- the only in-project read of the environment.

Purity: configuration; validated at startup, the only in-project reader of the environment.

AD-20 splits storage into three files: the read model, the record store, and the
semantic index build target. Their locations are deployment facts, so they are read
here and nowhere else -- an ``os.environ`` lookup in an adapter is the ambient
configuration the spine forbids, and it is what makes a test depend on the machine it
runs on.

There is **no default directory**. A missing setting raises rather than falling back to
a path under the working directory, because a silent fallback is how a production
process quietly answers from an empty database it created itself.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "DATABASE_DIR_ENV",
    "READ_MODEL_FILENAME",
    "RECORD_STORE_FILENAME",
    "SEMANTIC_INDEX_FILENAME",
    "ConfigError",
    "DatabasePaths",
]

#: The one environment variable this module reads. One directory rather than three
#: paths: three independently settable paths are three chances to point two of them at
#: the same file, which AD-20's separation exists to prevent.
DATABASE_DIR_ENV: Final = "ASKAI_DATABASE_DIR"

READ_MODEL_FILENAME: Final = "read_model.sqlite3"
RECORD_STORE_FILENAME: Final = "record_store.sqlite3"
SEMANTIC_INDEX_FILENAME: Final = "semantic_index.sqlite3"


class ConfigError(RuntimeError):
    """A setting the process cannot start without is missing or unusable."""


@dataclass(frozen=True, slots=True)
class DatabasePaths:
    """The three database files, resolved to absolute paths.

    Frozen, and built by one of the two constructors below rather than field by field,
    so "three distinct files" is a property of the type rather than a convention the
    caller is asked to honour.
    """

    read_model: Path
    record_store: Path
    semantic_index: Path

    def __post_init__(self) -> None:
        # Two names for one file would put the index rebuild back under the same
        # single-writer lock as live records -- exactly the failure AD-20 separates
        # the files to make impossible. Caught here, not at first write.
        paths = (self.read_model, self.record_store, self.semantic_index)
        if len(set(paths)) != len(paths):
            raise ConfigError(
                f"the three databases must be three distinct files, got {[str(p) for p in paths]}"
            )

    @classmethod
    def beneath(cls, directory: Path | str) -> DatabasePaths:
        """The three databases inside *directory*, named by the constants above.

        The directory need not exist yet; the schema step creates it. Paths are made
        absolute here so a later ``chdir`` cannot repoint a database mid-process.
        """
        base = Path(directory).resolve()
        return cls(
            read_model=base / READ_MODEL_FILENAME,
            record_store=base / RECORD_STORE_FILENAME,
            semantic_index=base / SEMANTIC_INDEX_FILENAME,
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> DatabasePaths:
        """Read ``ASKAI_DATABASE_DIR``, or fail loudly.

        *environ* is injectable so a test can state the environment it means rather
        than mutating the process's -- which is shared state between tests and the
        reason "it passes alone but not in the suite" happens.
        """
        env = os.environ if environ is None else environ
        raw = env.get(DATABASE_DIR_ENV, "").strip()
        if not raw:
            raise ConfigError(
                f"{DATABASE_DIR_ENV} is not set; it names the directory holding the "
                "read model, the record store and the semantic index. There is no "
                "default -- a process must be told where its data lives."
            )
        return cls.beneath(raw)
