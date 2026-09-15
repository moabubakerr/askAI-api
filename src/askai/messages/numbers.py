"""How a figure is written, per language, from the catalogue rather than from code.

Purity: data, imports nothing in-project.

FR-62 puts number formatting on the Arabic side of the bilingual contract, and the
three things that differ between the two languages -- the digit shapes, the group
separator and the decimal separator -- are **data**, declared in the ``numbers:`` block
of each catalogue file. That is deliberate: which numerals Arabic output uses is an
editorial decision the same reviewers make about the wording (FR-63a), and national
statistical publishing in the region has changed direction on it more than once.
Hard-coding either choice would make it a code change; declaring it makes it a diff.

Both files currently declare Western digits, including the Arabic one. That matches the
published data, the period strings -- which reject Arabic-Indic digits outright, so a
period and a figure would otherwise disagree within one sentence -- and R-174's own
worked examples, which are written ``3 مؤشرات``. The Arabic file declares the Arabic
thousands and decimal separators, U+066C and U+066B, so grouping follows the Arabic
convention even while the digits are shared.

Values arrive as ``int`` or ``Decimal`` and never as ``float``: a published value that
has been through binary floating point is no longer the published value (AD-4). This is
grouping and digit substitution only -- it does not round, and it does not choose a
precision. AD-18's single ``Formatter`` in ``assemble/`` owns those, and a second
opinion here would be the duplicate it exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

__all__ = ["NumberFormat", "format_number"]

_ASCII_DIGITS: Final = "0123456789"


@dataclass(frozen=True, slots=True)
class NumberFormat:
    """One language's numeral conventions, as declared in its catalogue file."""

    digits: str
    group_separator: str
    decimal_separator: str
    group_size: int

    def __post_init__(self) -> None:
        if len(self.digits) != 10:
            raise ValueError(
                f"digits must name all ten numerals in order, got {self.digits!r}"
            )
        if len(set(self.digits)) != 10:
            raise ValueError(f"digits must be ten distinct numerals, got {self.digits!r}")
        if self.group_size < 1:
            raise ValueError(f"group_size must be at least 1, got {self.group_size}")
        if not self.decimal_separator:
            # An empty decimal separator would join the whole and fractional parts into
            # a single number a hundred times too large, silently.
            raise ValueError("decimal_separator must not be empty")


def format_number(fmt: NumberFormat, value: int | Decimal) -> str:
    """Write *value* using *fmt*'s digits and separators, with no rounding.

    The digits of a number are written left to right in Arabic as in English, so the
    grouping below is direction-agnostic; the bidirectional algorithm in the reader's
    display handles placement, and inserting marks here would corrupt the string for
    every consumer that is not a browser.
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise TypeError(
            f"format_number takes an int or Decimal, not {type(value).__name__}; "
            "a float has already lost the published value"
        )
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError(f"format_number takes a finite Decimal, not {value}")

    # `format(..., "f")` rather than `str()`: `str(Decimal("1E+3"))` is "1E+3", and a
    # figure rendered in exponent notation is not a figure any reader asked for.
    plain = format(value, "f") if isinstance(value, Decimal) else str(value)
    negative = plain.startswith("-")
    whole, dot, fraction = (plain[1:] if negative else plain).partition(".")

    grouped = _group(whole, fmt.group_separator, fmt.group_size)
    body = grouped + (fmt.decimal_separator + fraction if dot else "")
    # The minus stays U+002D and is not translated: it is not a digit, and the
    # separators are the only punctuation the catalogue has an opinion about.
    return ("-" if negative else "") + _to_digits(body, fmt.digits)


def _group(whole: str, separator: str, size: int) -> str:
    if not separator:
        return whole
    head = len(whole) % size or size
    parts = [whole[:head]] + [whole[i : i + size] for i in range(head, len(whole), size)]
    return separator.join(parts)


def _to_digits(rendered: str, digits: str) -> str:
    if digits == _ASCII_DIGITS:
        return rendered
    return rendered.translate(str.maketrans(_ASCII_DIGITS, digits))
