"""Published content, decoded and rendered to text **once**, at ingest.

Purity: IO-adjacent (pure functions, called only by the ingest).

FR-64. The export carries its prose in three encodings at once: plain text, CMS-authored
HTML (139 of 289 published definitions), and base64 of HTML (58 of 104 entity
descriptions, 8 of 16 sector descriptions). Some of it came through a PDF, which leaves
a hyphenated word split across what used to be a line break -- ``second- lowest``.

All of that is undone here, when the row is stored. **No reader-facing path strips
markup**: by the time a figure or a definition reaches a composer it is already text, so
there is no answer-time step to forget, to do differently in Arabic, or to do twice.

The order is markup, then entities -- the same order as the domain's emptiness
predicate, and for the same reason. Decoding first would turn an *escaped* tag, which is
an angle bracket the author typed and wanted shown, into a real tag, and then delete it.

Emptiness is not decided here. ``is_published_text`` in the domain is the single
predicate for that, and this module calls it rather than carrying a second opinion about
what ``<p>&nbsp;</p>`` means.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from typing import Final

from askai.domain.text import is_published_text

__all__ = ["published_text"]

# CMS-authored HTML, not arbitrary markup, so a non-greedy angle-bracket span is all of
# it. Replaced with a space rather than deleted: `<p>a</p><p>b</p>` is two paragraphs,
# and deleting the tags would fuse them into one word.
_MARKUP: Final = re.compile(r"<[^>]*>")

#: U+00AD SOFT HYPHEN. A rendering hint that shows as nothing unless the line happens to
#: break there, so it is a character the export carries and the reader never saw.
_SOFT_HYPHEN: Final = "­"

# A hyphen with whitespace after it, between two letters: the PDF's line break, carried
# in as a space. The hyphen is kept, because the measured cases are hyphenated compounds
# split across a line ("second- lowest", "data- other"), not words split mid-stem.
_SPLIT_HYPHEN: Final = re.compile(r"(?<=[^\W\d_])-\s+(?=[^\W\d_])")

# The zero-width characters `str.split()` does not know about. `\s` already covers the
# no-break, quad, thin, line- and paragraph-separator spaces, so none of those repeat
# here. Codepoints rather than characters: two members either side of a `-` inside a
# character class silently become a range, and no linter reports the difference.
_ZERO_WIDTH_CODEPOINTS: Final = (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF)

_BLANK: Final = re.compile(
    r"[\s" + "".join(re.escape(chr(codepoint)) for codepoint in _ZERO_WIDTH_CODEPOINTS) + "]+"
)

# A base64 blob is one unbroken token. Published prose is not, in either language, so
# requiring the candidate to contain no whitespace is what keeps a short plain sentence
# from being decoded into nonsense.
_BASE64_TOKEN: Final = re.compile(r"[A-Za-z0-9+/]+={0,2}")

#: Shorter than this and a base64 round-trip is more likely a coincidence than an
#: encoding -- "Indicators" is not base64, but four letters of it would decode.
_MIN_BASE64_LENGTH: Final = 16


def _decoded(raw: str) -> str:
    """*raw* decoded if it is base64 of text, otherwise *raw* unchanged.

    Strict on purpose: one whitespace-free token, a length base64 can actually produce,
    valid under ``validate=True``, decodable as UTF-8, and decoding to something that
    looks like prose or markup. A guess here would corrupt a published definition
    silently, which is worse than leaving an encoded one to fail visibly.
    """
    candidate = raw.strip()
    if len(candidate) < _MIN_BASE64_LENGTH or len(candidate) % 4:
        return raw
    if not _BASE64_TOKEN.fullmatch(candidate):
        return raw
    try:
        decoded = base64.b64decode(candidate, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return raw
    if "<" not in decoded and not any(character.isspace() for character in decoded):
        return raw
    return decoded


def published_text(raw: str | None) -> str | None:
    """*raw* as the text a reader would have seen, or ``None`` if it says nothing.

    ``None`` rather than the empty string: an absent definition is absent, and a caller
    that has to tell "" from "not published" would be re-deciding the emptiness question
    the domain already answers.
    """
    if raw is None:
        return None
    decoded = _decoded(raw)
    if not is_published_text(decoded):
        return None
    without_markup = _MARKUP.sub(" ", decoded)
    unescaped = html.unescape(without_markup).replace(_SOFT_HYPHEN, "")
    rejoined = _SPLIT_HYPHEN.sub("-", unescaped)
    text = _BLANK.sub(" ", rejoined).strip()
    return text or None
