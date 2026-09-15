"""The single predicate for "is there published text here?".

Purity: pure, imports nothing in-project.

The published CMS columns encode absence in several ways at once: a genuinely
empty string, a bare ``<p></p>`` wrapper the editor leaves behind, a wrapper
holding nothing but ``&nbsp;``, and a lone dash typed in to mean "nothing to
say". All of them are absence, and every call site in the engine has to agree
on that, or a gap becomes commentary in one layer and silence in another.

So there is **exactly one** predicate, it lives here, and it is strict:

1. strip markup -- a tag is structure, never text;
2. decode HTML entities -- ``&nbsp;`` is whitespace, not content;
3. collapse and strip whitespace, including the non-breaking, zero-width and
   soft kinds the export carries;
4. treat a bare hyphen or en dash as absent.

**Markup is stripped before entities are decoded**, which is the order that renders
markup to text rather than the reverse. Decoding first would turn an *escaped* tag --
``&lt;p&gt;``, which is a literal angle bracket the author typed and wanted to show --
into a real tag, and then delete it, reading published text as absent.

A non-empty remainder is text. ``tests/test_domain_invariants.py`` asserts
there is no second implementation.
"""

from __future__ import annotations

import html
import re
from typing import Final

__all__ = ["is_published_text"]

# Tags are structure. The export is CMS-authored HTML, not arbitrary markup, so a
# non-greedy angle-bracket span is the whole of it.
_MARKUP: Final = re.compile(r"<[^>]*>")

# `str.strip()` does not know about the zero-width characters the export carries, and
# those are exactly what an "empty" rich-text field is made of. Python's `\s` already
# covers U+00A0 no-break space, U+1680, the U+2000-U+200A quad and thin spaces, U+2028,
# U+2029, U+202F, U+205F, U+3000 and the ASCII set, so none of those is repeated here.
#
# These are codepoints rather than characters written into a class on purpose. A regex
# character class is adjacency-sensitive -- two members written either side of a `-`
# silently become a *range*, and neither ruff nor mypy reports the difference. Integers
# cannot be adjacent to anything, so the set below means exactly what it lists.
_ZERO_WIDTH_CODEPOINTS: Final = (
    0x00AD,  # soft hyphen -- renders as nothing unless the line happens to break
    0x200B,  # zero width space
    0x200C,  # zero width non-joiner
    0x200D,  # zero width joiner
    0x2060,  # word joiner
    0xFEFF,  # zero width no-break space
)

_BLANK: Final = re.compile(
    r"[\s" + "".join(re.escape(chr(codepoint)) for codepoint in _ZERO_WIDTH_CODEPOINTS) + "]+"
)

# A lone dash is the editor writing "nothing to say" rather than leaving the field
# alone. Only the two forms the published data actually uses are treated this way:
# U+002D hyphen-minus and U+2013 en dash.
_ABSENT: Final = frozenset({chr(0x002D), chr(0x2013)})


def is_published_text(raw: str | None) -> bool:
    """Is *raw* substantive published text, rather than an empty rich-text shell?

    Returns ``False`` for ``None``, for the empty string, for markup with no
    content (``<p></p>``, ``<p>&nbsp;</p>``), for whitespace of any kind, and
    for a bare hyphen or en dash. Returns ``True`` for anything else.
    """
    if raw is None:
        return False
    without_markup = _MARKUP.sub(" ", raw)
    decoded = html.unescape(without_markup)
    collapsed = _BLANK.sub(" ", decoded).strip()
    if not collapsed:
        return False
    return collapsed not in _ABSENT
