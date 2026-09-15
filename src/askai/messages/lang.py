"""``Lang`` -- the one place the answer's language is named.

Purity: data, imports nothing in-project.

A type rather than a bare ``"en"``/``"ar"`` string, because AD-11's language rule is
that ``Lang`` is an *explicit argument* through every rendering path -- never inferred
at the point of use, never a global. A closed enum is what makes that checkable: a
signature that takes a ``Lang`` cannot be satisfied by a default, and a call site that
has not been given one cannot invent it from a locale, a request header or a module
variable.

There is deliberately no ``DEFAULT``, no ``from_request()`` and no ``current()``. Each
would be the global arriving under a different name, and FR-61 -- answer in the
language of the question -- is only true if the question's language is carried, not
guessed.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["Lang"]


class Lang(StrEnum):
    """A language the engine answers in. The value is the catalogue file's stem."""

    EN = "en"
    AR = "ar"
