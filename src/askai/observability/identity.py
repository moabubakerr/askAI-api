"""The caller identity the engine records but never establishes.

Purity: pure.

AD-24: the engine owns no session, login or user store. It consumes an identity the
surrounding platform asserts and records it with the answer. The decision's sharp edge
is the negative case -- *"a request arriving with no asserted identity is recorded as
anonymous, and that fact is itself recorded rather than assumed away"* -- so anonymity
is a value here with a stated reason, not a missing field.

Two states, and no third. A blank string, a whitespace id or an empty header is not a
weak identity: it is no identity, and ``caller_identity`` turns each of them into
``Anonymous`` with the reason recorded. Without that, a record would carry ``caller_id
= ''`` and be indistinguishable from one whose platform asserted nothing -- which is
precisely the "auditable but not attributable" ambiguity AD-24 asks to be made visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
    "MAX_ID_CHARS",
    "Anonymous",
    "Asserted",
    "CallerIdentity",
    "IdentityError",
    "caller_identity",
]

#: The longest identifier the record accepts, for every id it stores. A bound on the
#: record is only real if the caller cannot hand it an unbounded string, and an
#: identity is caller-supplied by definition (AD-24). Long enough for a subject claim
#: or an opaque gateway id; short enough that no arrangement of ids can dominate a
#: record's size.
MAX_ID_CHARS: Final = 128

#: What is recorded when the platform asserted nothing at all.
NOT_ASSERTED: Final = "no identity asserted by the platform"

#: What is recorded when something arrived but was not usable as an identity.
BLANK_ASSERTION: Final = "the platform asserted a blank identity"

#: What is recorded when the asserted id is longer than a record may store.
OVERLONG_ASSERTION: Final = "the platform asserted an identity longer than the record accepts"


class IdentityError(ValueError):
    """An identity value that cannot be recorded as given."""


@dataclass(frozen=True, slots=True)
class Asserted:
    """The platform said who this is, and the record says so with it."""

    caller_id: str

    def __post_init__(self) -> None:
        if not self.caller_id.strip():
            raise IdentityError(
                "Asserted requires a caller id; an identity that is blank is Anonymous, "
                "and saying so is the whole of AD-24's negative case"
            )
        if len(self.caller_id) > MAX_ID_CHARS:
            raise IdentityError(
                f"caller id is {len(self.caller_id)} characters, the record stores at "
                f"most {MAX_ID_CHARS}; use caller_identity() to turn an unusable "
                "assertion into a recorded Anonymous rather than a failed answer"
            )


@dataclass(frozen=True, slots=True)
class Anonymous:
    """No usable identity was asserted -- and *why* is recorded, not inferred later."""

    reason: str = NOT_ASSERTED

    def __post_init__(self) -> None:
        if not self.reason.strip():
            raise IdentityError("Anonymous requires a reason; that fact is the record")


type CallerIdentity = Asserted | Anonymous


def caller_identity(asserted: str | None) -> CallerIdentity:
    """Turn what the platform asserted -- or did not -- into a recordable identity.

    Total: every input yields a value, because a request that reached the engine is
    going to be answered, and an unusable identity must degrade to a recorded fact
    rather than to an error the reader sees (AD-24, AD-15). The three ways an identity
    can be absent are kept distinct, since "nothing arrived" and "something arrived and
    was empty" mean different things to whoever later asks why an answer is not
    attributable.
    """
    if asserted is None:
        return Anonymous(NOT_ASSERTED)
    if not asserted.strip():
        return Anonymous(BLANK_ASSERTION)
    if len(asserted) > MAX_ID_CHARS:
        return Anonymous(OVERLONG_ASSERTION)
    return Asserted(asserted)
