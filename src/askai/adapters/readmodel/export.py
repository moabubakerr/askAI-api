"""The CMS export on disk, read as tables. Nothing here interprets a column.

Purity: IO.

The export is two layers in one directory (DATA-CONTRACT §1.0): the ``P*`` files are the
published layer, which is the only answerable one, and the ``Item_*`` files are the CMS
working set, which has no grain column, no Arabic analysis and no unit. This module
names both, because refusing well requires knowing what exists; :mod:`ingest` reads only
the published accessors and :mod:`unpublished` reads only the base one.

Filenames carry the export timestamp, so a file is located by its stable prefix and an
ambiguous or missing prefix is an error rather than a first-match guess. Two of the
published files are zero bytes in this export (``P10``, ``P11``); neither is read here.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ["CMS_SUBDIRECTORY", "CmsExport", "ExportError", "Row"]

#: One export row, exactly as the CSV spells it. Values are strings or nothing else --
#: every interpretation (a period, a decimal, a flag) happens in the ingest, once.
type Row = dict[str, str]

#: The published CMS tables live in a subdirectory of the export root; the loose
#: non-CMS files -- the two group-name sources -- sit beside it.
CMS_SUBDIRECTORY: Final = "cms"

_INDICATORS: Final = "P01_Published_Indicators"
_DETAILS: Final = "P02_Published_IndicatorDetails"
_DATAPOINTS: Final = "P03_Published_DataPoints"
_ANALYSES: Final = "P04_Published_DataPointAnalysis"
_LOOKUPS: Final = "P12_Ref_Lookups_Common"
_PRIORITY_TYPES: Final = "P13_Ref_IndicatorPriorityTypes"
_COUNTRIES: Final = "P14_Ref_Countries"
_BASE_INDICATORS: Final = "Item_2_Indicators_Catalog"

_SECTORS: Final = "Sectors.csv"
_GENERAL_ENTITIES: Final = "General Entities.csv"


class ExportError(RuntimeError):
    """The export directory is not the one this build reads."""


def _read(path: Path) -> tuple[Row, ...]:
    # utf-8-sig: every file in this export starts with a byte-order mark, and reading it
    # as utf-8 would leave it glued to the first column name, where it breaks a lookup
    # that looks exactly right in the source.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return tuple(
            {str(key): str(value or "") for key, value in row.items()}
            for row in csv.DictReader(handle)
        )


@dataclass(frozen=True, slots=True)
class CmsExport:
    """One export on disk: the CMS tables, and the two loose group-name files."""

    cms_directory: Path
    loose_directory: Path

    @classmethod
    def rooted(cls, root: Path | str) -> CmsExport:
        """The export laid out as it ships: CMS tables under ``cms/``, loose files above."""
        base = Path(root).resolve()
        return cls(cms_directory=base / CMS_SUBDIRECTORY, loose_directory=base)

    def _by_prefix(self, prefix: str) -> tuple[Row, ...]:
        matches = sorted(self.cms_directory.glob(f"{prefix}*.csv"))
        if not matches:
            raise ExportError(
                f"no file named {prefix}*.csv in {self.cms_directory}; the export is "
                "incomplete, and an incomplete export is not partially ingested"
            )
        if len(matches) > 1:
            raise ExportError(
                f"{len(matches)} files match {prefix}*.csv in {self.cms_directory} "
                f"({[path.name for path in matches]}); two exports in one directory "
                "would be ingested as one"
            )
        return _read(matches[0])

    def _loose(self, filename: str) -> tuple[Row, ...]:
        path = self.loose_directory / filename
        if not path.is_file():
            raise ExportError(f"{path} is missing; it is one of the two group-name sources")
        return _read(path)

    # ------------------------------------------------------------- the published layer

    def published_indicators(self) -> tuple[Row, ...]:
        """The catalogue -- what a reader can name."""
        return self._by_prefix(_INDICATORS)

    def published_details(self) -> tuple[Row, ...]:
        """The measurables, carrying unit, polarity, format and source."""
        return self._by_prefix(_DETAILS)

    def published_datapoints(self) -> tuple[Row, ...]:
        """The numbers, one per detail, period and country."""
        return self._by_prefix(_DATAPOINTS)

    def published_analyses(self) -> tuple[Row, ...]:
        """What an analyst wrote about one datapoint."""
        return self._by_prefix(_ANALYSES)

    def reference_lookups(self) -> tuple[Row, ...]:
        """The ten common lookup vocabularies -- units, polarities, sources and the rest."""
        return self._by_prefix(_LOOKUPS)

    def reference_priority_types(self) -> tuple[Row, ...]:
        """The priority vocabulary, which is also the confidentiality gate."""
        return self._by_prefix(_PRIORITY_TYPES)

    def reference_countries(self) -> tuple[Row, ...]:
        """The country reference. Its rows are named; a datapoint's country is not."""
        return self._by_prefix(_COUNTRIES)

    def entity_names(self) -> tuple[Row, ...]:
        """The group names, which live outside the CMS tables in two files, not one."""
        return (*self._loose(_SECTORS), *self._loose(_GENERAL_ENTITIES))

    # ------------------------------------------------------------------ the base layer

    def base_indicators(self) -> tuple[Row, ...]:
        """Every indicator the CMS holds, approved or not. Names and flags only."""
        return self._by_prefix(_BASE_INDICATORS)
