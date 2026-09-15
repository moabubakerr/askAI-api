"""Bilingual strings: en.yaml, ar.yaml and the catalogue loader.

Purity: data.

Every word the engine says to a reader is an id in ``data/en.yaml`` and ``data/ar.yaml``
plus the parameters a caller supplies (FR-63, AD-11). Nothing outside this package
holds reader-facing text, and ``tests/test_messages.py`` asserts it.

The two files are one reviewable artifact in two halves (FR-63a): they are diffed and
agreed by the people who agree the rules, and a wording fix is a change to data with no
code touched. ``load_catalogue`` refuses to return a catalogue whose halves disagree --
an id in one language and not the other stops startup, because the alternative is an
English sentence surfacing inside an Arabic answer on the one question nobody tried.

``Lang`` is an argument on every function here and there is no default anywhere in the
package. A call site that has not been handed the question's language cannot render.
"""

from __future__ import annotations

from askai.messages.catalogue import (
    CATALOGUE_VERSION,
    Catalogue,
    CatalogueError,
    Counted,
    Entry,
    Plain,
    load_catalogue,
)
from askai.messages.lang import Lang
from askai.messages.numbers import NumberFormat, format_number
from askai.messages.plural import REQUIRED_CATEGORIES, PluralCategory, plural_category
from askai.messages.render import (
    compose_counted,
    format_value,
    render,
    render_counted,
    render_period,
)

__all__ = [
    "CATALOGUE_VERSION",
    "REQUIRED_CATEGORIES",
    "Catalogue",
    "CatalogueError",
    "Counted",
    "Entry",
    "Lang",
    "NumberFormat",
    "Plain",
    "PluralCategory",
    "compose_counted",
    "format_number",
    "format_value",
    "load_catalogue",
    "plural_category",
    "render",
    "render_counted",
    "render_period",
]
