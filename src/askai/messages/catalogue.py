"""The bilingual catalogue, loaded and validated once, or the service does not start.

Purity: data; reads the two packaged YAML files and imports nothing above ``domain/``.

AD-11 makes every reader-facing string a message id plus parameters, held in versioned
data files rather than in code. The whole value of that is lost the moment the two
files can drift: an id present in ``en.yaml`` and absent from ``ar.yaml`` is an English
sentence waiting to appear in an Arabic answer, and it would appear on the one question
nobody tried. So the loader treats **drift as a startup failure**, not as a fallback:

* the id sets must be identical, both ways;
* an id must be the same *kind* in both files -- a plain string in one and a counted
  message in the other is the same drift wearing a different shape;
* a counted message must supply exactly the plural categories its own language can
  produce (R-174), so an Arabic message without its dual never reaches a reader;
* the substitution fields must be spellable -- ``{count}``, not ``{0}`` or ``{a.b}`` --
  so a wording fix cannot reach into a parameter object.

What it deliberately does **not** do is require the two languages to use the same
fields in the same forms. ``one: مؤشر واحد`` carries no digit at all while
``few: {count} مؤشرات`` does, and forcing them to match would force the digit back
into a form Arabic writes without one. The message's parameter set is therefore the
union across both languages, and every render supplies all of it.

There is no in-module cache and no module-level catalogue object. Startup loads one and
passes it; a global here would be the second way to reach reader text, and the first
step back towards a string literal at the point of use.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from string import Formatter
from types import MappingProxyType
from typing import Final

import yaml

from askai.messages.lang import Lang
from askai.messages.numbers import NumberFormat
from askai.messages.plural import REQUIRED_CATEGORIES, PluralCategory

__all__ = [
    "CATALOGUE_VERSION",
    "Catalogue",
    "CatalogueError",
    "Counted",
    "Entry",
    "Plain",
    "load_catalogue",
]

#: The catalogue file's shape version. A change to the sections below increments it,
#: and a file declaring anything else fails to start rather than being read against a
#: shape it was not written for -- the same contract ``SPEC_VERSION`` carries.
CATALOGUE_VERSION: Final = 1

_DATA_DIR: Final = "data"
_SECTIONS: Final = frozenset({"version", "numbers", "messages"})
_NUMBER_FIELDS: Final = ("digits", "group_separator", "decimal_separator", "group_size")

#: Supplied by the renderers rather than by the caller, so a message may use them
#: without the caller being asked to pass them.
RESERVED_FIELDS: Final = frozenset({"count", "counted"})


class CatalogueError(Exception):
    """The catalogue cannot be trusted to render. Raised at load, and at render for an
    id or a parameter set the catalogue does not have -- never swallowed into a
    placeholder, which is how a missing translation reaches a reader looking deliberate.
    """


@dataclass(frozen=True, slots=True)
class Plain:
    """A message whose wording does not depend on a count."""

    text: str


@dataclass(frozen=True, slots=True)
class Counted:
    """A message with one wording per plural category of its language (R-174)."""

    forms: Mapping[PluralCategory, str]


type Entry = Plain | Counted


@dataclass(frozen=True, slots=True)
class Catalogue:
    """Both languages, validated against each other, immutable from here on."""

    entries: Mapping[Lang, Mapping[str, Entry]]
    numbers: Mapping[Lang, NumberFormat]
    fields: Mapping[str, frozenset[str]]
    version: int = CATALOGUE_VERSION

    def entry(self, lang: Lang, message_id: str) -> Entry:
        """The wording of *message_id* in *lang*.

        ``lang`` is an argument and not a property of the catalogue: one loaded
        catalogue serves every request, and a request's language belongs to the
        question, never to the process (FR-61).
        """
        try:
            return self.entries[lang][message_id]
        except KeyError:
            raise CatalogueError(
                f"no message {message_id!r} in the catalogue; reader-facing text comes "
                "from messages/data, so add the id to both files"
            ) from None

    def parameters(self, message_id: str) -> frozenset[str]:
        """The fields every render of *message_id* must supply, in either language."""
        try:
            return self.fields[message_id]
        except KeyError:
            raise CatalogueError(f"no message {message_id!r} in the catalogue") from None


def load_catalogue(source: Traversable | None = None) -> Catalogue:
    """Read, validate and freeze both language files, or raise ``CatalogueError``.

    *source* is the directory holding ``en.yaml`` and ``ar.yaml``; it defaults to the
    one packaged beside this module. It exists so a test can point at a deliberately
    broken pair and assert the loader refuses it -- the behaviour the acceptance
    criterion is about -- without shipping the broken pair.
    """
    root = source if source is not None else files("askai.messages").joinpath(_DATA_DIR)

    documents = {lang: _read(root, lang) for lang in Lang}
    numbers = {lang: _number_format(lang, documents[lang]) for lang in Lang}
    raw_messages = {lang: _messages_section(lang, documents[lang]) for lang in Lang}

    _check_ids_match(raw_messages)
    entries = {lang: _entries(lang, raw_messages[lang]) for lang in Lang}
    _check_kinds_match(entries)

    return Catalogue(
        entries=MappingProxyType({lang: MappingProxyType(entries[lang]) for lang in Lang}),
        numbers=MappingProxyType(numbers),
        fields=MappingProxyType(_fields_by_id(entries)),
    )


# ------------------------------------------------------------------ reading the files


def _read(root: Traversable, lang: Lang) -> Mapping[str, object]:
    path = root.joinpath(f"{lang.value}.yaml")
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise CatalogueError(
            f"the {lang.value} catalogue is missing or unreadable at {path!s}; "
            "the engine does not start without both languages"
        ) from exc
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise CatalogueError(f"the {lang.value} catalogue is not valid YAML: {exc}") from exc

    if not isinstance(document, dict):
        raise CatalogueError(
            f"the {lang.value} catalogue must be a mapping of sections, "
            f"got {type(document).__name__}"
        )
    keys = {str(key) for key in document}
    if keys != _SECTIONS:
        missing = ", ".join(sorted(_SECTIONS - keys)) or "nothing"
        unknown = ", ".join(sorted(keys - _SECTIONS)) or "nothing"
        raise CatalogueError(
            f"the {lang.value} catalogue must hold exactly {sorted(_SECTIONS)}; "
            f"missing {missing}, unexpected {unknown}"
        )
    version = document["version"]
    if version != CATALOGUE_VERSION:
        raise CatalogueError(
            f"the {lang.value} catalogue declares version {version!r}; this build "
            f"reads version {CATALOGUE_VERSION}"
        )
    return {str(key): value for key, value in document.items()}


def _number_format(lang: Lang, document: Mapping[str, object]) -> NumberFormat:
    block = document["numbers"]
    if not isinstance(block, dict):
        raise CatalogueError(f"the {lang.value} numbers section must be a mapping")
    keys = {str(key) for key in block}
    if keys != set(_NUMBER_FIELDS):
        raise CatalogueError(
            f"the {lang.value} numbers section must declare exactly "
            f"{list(_NUMBER_FIELDS)}, got {sorted(keys)}"
        )
    digits, group, decimal, size = (block[field] for field in _NUMBER_FIELDS)
    if not (isinstance(digits, str) and isinstance(group, str) and isinstance(decimal, str)):
        raise CatalogueError(f"the {lang.value} numeral conventions must be strings")
    if not isinstance(size, int) or isinstance(size, bool):
        raise CatalogueError(f"the {lang.value} group_size must be a whole number")
    try:
        return NumberFormat(
            digits=digits, group_separator=group, decimal_separator=decimal, group_size=size
        )
    except ValueError as exc:
        raise CatalogueError(f"the {lang.value} numeral conventions are invalid: {exc}") from exc


def _messages_section(lang: Lang, document: Mapping[str, object]) -> Mapping[str, object]:
    block = document["messages"]
    if not isinstance(block, dict):
        raise CatalogueError(f"the {lang.value} messages section must be a mapping of ids")
    if not block:
        raise CatalogueError(f"the {lang.value} catalogue has no messages")
    return {str(key): value for key, value in block.items()}


# -------------------------------------------------------------------- the two checks


def _check_ids_match(raw: Mapping[Lang, Mapping[str, object]]) -> None:
    """The acceptance criterion: a key in one language and not the other stops startup.

    Reported in both directions in one message. Told only which side is short, whoever
    is fixing it has to run the loader again to learn the other half.
    """
    ids = {lang: frozenset(raw[lang]) for lang in Lang}
    shared = frozenset.intersection(*ids.values())
    lopsided = {lang: sorted(ids[lang] - shared) for lang in Lang if ids[lang] - shared}
    if lopsided:
        detail = "; ".join(
            f"only in {lang.value}: {', '.join(only)}" for lang, only in lopsided.items()
        )
        raise CatalogueError(
            f"the language files disagree on which messages exist -- {detail}. "
            "Every id exists in every language or the engine does not start"
        )


def _check_kinds_match(entries: Mapping[Lang, Mapping[str, Entry]]) -> None:
    reference, *others = list(Lang)
    for message_id, entry in entries[reference].items():
        for lang in others:
            other = entries[lang][message_id]
            if type(entry) is not type(other):
                raise CatalogueError(
                    f"message {message_id!r} is counted in one language and not in "
                    f"another ({reference.value}: {type(entry).__name__}, "
                    f"{lang.value}: {type(other).__name__}); a count either agrees "
                    "with the noun in every language or in none"
                )


# ------------------------------------------------------------------ building entries


def _entries(lang: Lang, raw: Mapping[str, object]) -> dict[str, Entry]:
    return {message_id: _entry(lang, message_id, value) for message_id, value in raw.items()}


def _entry(lang: Lang, message_id: str, value: object) -> Entry:
    if isinstance(value, str):
        _check_fields(lang, message_id, value)
        used = _template_fields(value) & RESERVED_FIELDS
        if used:
            # `count` and `counted` are supplied by the counted renderers. A message
            # that is not counted never meets one, so this would render a hole.
            raise CatalogueError(
                f"message {message_id!r} in {lang.value} uses {sorted(used)}, which "
                "only a counted message receives; give it a form per plural category"
            )
        return Plain(text=value)
    if isinstance(value, dict):
        return Counted(forms=MappingProxyType(_forms(lang, message_id, value)))
    raise CatalogueError(
        f"message {message_id!r} in {lang.value} must be a string, or a mapping of "
        f"plural category to string, not {type(value).__name__}"
    )


def _forms(
    lang: Lang, message_id: str, value: Mapping[object, object]
) -> dict[PluralCategory, str]:
    required = REQUIRED_CATEGORIES[lang]
    named = {str(key) for key in value}
    unknown = named - {category.value for category in PluralCategory}
    if unknown:
        raise CatalogueError(
            f"message {message_id!r} in {lang.value} names plural categories that do "
            f"not exist: {sorted(unknown)}"
        )
    supplied = {PluralCategory(name) for name in named}
    if supplied != required:
        missing = sorted(category.value for category in required - supplied)
        extra = sorted(category.value for category in supplied - required)
        raise CatalogueError(
            f"counted message {message_id!r} in {lang.value} must supply exactly the "
            f"forms {lang.value} distinguishes; missing {missing or 'nothing'}, "
            f"unusable {extra or 'nothing'}"
        )
    forms: dict[PluralCategory, str] = {}
    for name, template in value.items():
        if not isinstance(template, str):
            raise CatalogueError(
                f"form {str(name)!r} of {message_id!r} in {lang.value} must be a string"
            )
        _check_fields(lang, message_id, template)
        forms[PluralCategory(str(name))] = template
    return forms


def _check_fields(lang: Lang, message_id: str, template: str) -> None:
    for _, field, spec, conversion in Formatter().parse(template):
        if field is None:
            continue
        if not field.isidentifier():
            raise CatalogueError(
                f"message {message_id!r} in {lang.value} uses the substitution "
                f"{{{field}}}; a message names a parameter, it does not index or "
                "reach into one"
            )
        if spec or conversion:
            raise CatalogueError(
                f"message {message_id!r} in {lang.value} formats {{{field}}} in the "
                "template; how a value is written is the caller's decision, made once"
            )


def _template_fields(template: str) -> frozenset[str]:
    return frozenset(
        field for _, field, _, _ in Formatter().parse(template) if field is not None
    )


def _fields_by_id(entries: Mapping[Lang, Mapping[str, Entry]]) -> dict[str, frozenset[str]]:
    """A message's parameters are the union over both languages and every form.

    Union rather than intersection, and not per-language: a caller renders one message
    with one parameter set regardless of which language it lands in, or the call site
    starts branching on language -- which is the inference AD-11 forbids.
    """
    fields: dict[str, set[str]] = {}
    for by_id in entries.values():
        for message_id, entry in by_id.items():
            templates = [entry.text] if isinstance(entry, Plain) else list(entry.forms.values())
            found = fields.setdefault(message_id, set())
            for template in templates:
                found.update(_template_fields(template))
    return {
        message_id: frozenset(found - RESERVED_FIELDS) for message_id, found in fields.items()
    }
