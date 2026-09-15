"""The export's country reference, handed to the reviewed alias table at ingest.

Purity: IO.

Story 4.1 leaves one seam open here on purpose. The alias table in ``rules/data`` is what
a steward maintains -- the *extra* spellings a reader might use -- and it deliberately
carries no Latin-script surface form for the country whose name may not appear anywhere
under ``src/askai/``. Those forms exist, they are published, and they arrive from the
export's own reference table at runtime rather than being typed into a file here.

So the ingest calls this, and the result is the map the answer path resolves country
names through. If nothing called it, that one country would be nameable in Arabic only.

The extension is checked, not merged: a reference name the reviewed table already gives
to a different code raises, because a reference table disagreeing with a reviewed group
is something a steward settles, not something an ingest silently overwrites.
"""

from __future__ import annotations

from askai.adapters.readmodel.export import CmsExport
from askai.rules.countries import CountryAliases, ReferenceCountry, country_aliases

__all__ = ["country_aliases_from", "reference_countries"]


def reference_countries(export: CmsExport) -> tuple[ReferenceCountry, ...]:
    """The published country reference, as the rule layer's own row type.

    The code is the identity: two published spellings of one country share it, which is
    how the duplicate the export carries collapses to one identity before any row is
    fetched. A row with no code contributes no spelling and is dropped by the extension.
    """
    return tuple(
        ReferenceCountry(
            code=row.get("Code", "").strip(),
            name_en=row.get("NameEN", "").strip(),
            name_ar=row.get("NameAR", "").strip(),
        )
        for row in export.reference_countries()
    )


def country_aliases_from(export: CmsExport, base: CountryAliases | None = None) -> CountryAliases:
    """The reviewed alias table, widened by the names *export* publishes.

    *base* of ``None`` uses the packaged table. It is injectable so a test can state the
    reviewed table it means rather than depending on the one that happens to ship.
    """
    reviewed = country_aliases() if base is None else base
    return reviewed.extended_with(reference_countries(export))
