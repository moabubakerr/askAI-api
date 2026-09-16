"""Packages, put in an order. Nothing here can look inside one, and that is the design.

Purity: orchestration; orders packages, never mutates one.

AD-10 gives this layer one job and forbids it the other: *"the response layer may order
and concatenate packages but never mutate or reach inside one."* An ``import-linter``
contract already stops ``respond/`` importing ``askai.narrate`` or ``askai.assemble``, so
this module cannot name the package type at all -- and that is why the functions below
are **generic**. They are written over an opaque ``T`` with the ordering key supplied by
the caller, because a layer that cannot mention ``AnswerPackage`` cannot read a field off
one, cannot rebuild one, and cannot merge two.

The consequence worth stating: every package that comes out is the *same object* that
went in, identity included. Ordering here is a permutation and nothing else, so an
approved package and an external one arrive at the client distinguishable -- which is the
whole reason AD-10 refuses to merge them (FR-96).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

__all__ = ["OrderingError", "concatenate", "ordered"]


class OrderingError(ValueError):
    """A package was handed in whose key the declared order does not cover.

    Raised rather than appended at the end. An unknown key silently sorting last is how
    a package of a kind nobody planned for reaches a reader in a position nobody chose,
    and the ordering is short enough that a gap in it is a gap in the response contract.
    """


def ordered[T](
    packages: Sequence[T], key: Callable[[T], str], order: Sequence[str]
) -> tuple[T, ...]:
    """*packages*, arranged by where ``key`` puts each one in *order*.

    Stable within a key, so two packages of the same kind keep the order they arrived
    in: the caller produced them in a deliberate sequence and this layer has no basis
    for a second opinion about it.

    ``key`` is a function rather than an attribute name so that nothing here performs an
    attribute access on a package -- ``getattr(package, "source")`` would be reaching
    inside one through a string, which is the contract defeated by spelling.
    """
    ranks = {name: rank for rank, name in enumerate(order)}
    unknown = sorted({key(package) for package in packages} - set(ranks))
    if unknown:
        raise OrderingError(
            f"the response order {list(order)} does not place {unknown}; a package kind "
            "the order does not cover has no position, and appending it silently would "
            "choose one for it"
        )
    return tuple(sorted(packages, key=lambda package: ranks[key(package)]))


def concatenate[T](*groups: Sequence[T]) -> tuple[T, ...]:
    """Every package from every group, in the order the groups were given.

    Concatenation, not combination: nothing is de-duplicated, summed or collapsed. Two
    packages saying different things about the same indicator both survive, because
    which of them a reader believes is a decision for the reader and not for this layer.
    """
    return tuple(package for group in groups for package in group)
