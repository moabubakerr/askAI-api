"""Loading ``data/*.yaml`` at startup, and refusing to start when one of them is wrong.

Purity: reads the packaged rule files once; pure thereafter.

AD-11's teeth are in the failure mode, not in the loading: *"they are schema-validated
at startup and the service **fails to start** on an invalid or missing file."* A loader
that skipped a malformed file, or defaulted a missing one, would leave the engine
answering with business logic nobody can see -- the founding defect, arrived at from the
other direction. So every failure here is a raised ``RuleLoadError`` naming the file and
the constraint it broke, and there is no path that returns a partial ``RuleSet``.

**Loaded is not fired.** ``load_rules()`` returns every rule in the files, ``rejected``
ones included, because ``R-157`` exists precisely so that the rule it records is not
re-proposed in eighteen months. Reaching for one to act on goes through ``fire()``,
which refuses a rejected rule by name. Status is otherwise not consulted: an ``agreed``
rule and a ``proposed`` rule are indistinguishable to this module, so agreement is a
data edit and never a deployment (Story 10.7 owns the gate that reads the status).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

import yaml
from pydantic import ValidationError

from askai.rules.schema import Rule, RuleFile, RuleStatus, RuleValue

__all__ = [
    "DATA_DIR",
    "LoadedRule",
    "RuleLoadError",
    "RuleRejectedError",
    "RuleSet",
    "load_rules",
    "rules",
]

#: The rule files ship inside the package, so the set the engine validates is the set
#: that was installed -- not whatever happens to sit in the working directory.
DATA_DIR: Final = Path(__file__).resolve().parent / "data"

_SUFFIX: Final = ".yaml"


class RuleLoadError(Exception):
    """A rule file is missing, unreadable, or does not answer to the schema.

    Typed and fatal. The message always names the file first, because the operator's
    next action is to open it.
    """


class RuleRejectedError(Exception):
    """Something asked to fire a rule the catalogue withdrew.

    Raised rather than returning ``None``: a rejected rule quietly yielding nothing is
    indistinguishable from a rule that never ran, which is the F9 class AD-15 forbids.
    """


@dataclass(frozen=True, slots=True)
class LoadedRule:
    """A rule and the file it came from.

    The provenance is carried rather than looked up: FR-70's enumerate output has to
    print the file, and a rule that cannot say where it lives is a rule an operator
    cannot go and change.
    """

    rule: Rule
    source_file: Path

    @property
    def id(self) -> str:
        return self.rule.id

    @property
    def statement(self) -> str:
        return self.rule.statement

    @property
    def status(self) -> RuleStatus:
        return self.rule.status


@dataclass(frozen=True, slots=True)
class RuleSet:
    """Every rule the engine implements, in id order, with its provenance.

    Iteration and ``all()`` include ``rejected`` rules; ``fire()`` is the only way to
    reach a rule in order to act on it, and it is the one place the rejection bites.
    """

    loaded: tuple[LoadedRule, ...]

    def __iter__(self) -> Iterator[LoadedRule]:
        return iter(self.loaded)

    def __len__(self) -> int:
        return len(self.loaded)

    @property
    def by_id(self) -> Mapping[str, LoadedRule]:
        return {entry.id: entry for entry in self.loaded}

    def get(self, rule_id: str) -> LoadedRule:
        """The rule with *rule_id*, whatever its status -- for enumerating and reviewing."""
        try:
            return self.by_id[rule_id]
        except KeyError:
            raise LookupError(
                f"{rule_id} is not a rule in {DATA_DIR.name}/; rule ids are stable and "
                "never reused, so a missing one is a typo or a rule that was never written"
            ) from None

    def fire(self, rule_id: str) -> Rule:
        """The rule with *rule_id*, for acting on.

        Refuses a ``rejected`` rule and no other status: ``proposed`` fires exactly as
        ``agreed`` does, so nothing here has to change when one is agreed.
        """
        entry = self.get(rule_id)
        if not entry.rule.is_fireable:
            raise RuleRejectedError(
                f"{rule_id} is rejected and is never fired; it is recorded so it is not "
                f"re-proposed -- {entry.rule.withdrawn_because}"
            )
        return entry.rule

    def value(self, rule_id: str, key: str) -> RuleValue:
        """One clause of a fireable rule, by name.

        The engine's single door to a reader-affecting constant. Reaching past it to a
        literal is what ``tests/test_rules.py`` scans ``compile/``, ``execute/`` and
        ``assemble/`` for.
        """
        rule = self.fire(rule_id)
        try:
            return rule.values[key]
        except KeyError:
            known = ", ".join(sorted(rule.values)) or "none"
            raise LookupError(f"{rule_id} has no value `{key}`; it carries: {known}") from None


def _read_file(path: Path) -> RuleFile:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RuleLoadError(f"{path}: cannot be read -- {error}") from error
    try:
        document = yaml.safe_load(raw)
    except yaml.YAMLError as error:
        raise RuleLoadError(f"{path}: is not readable YAML -- {error}") from error
    if not isinstance(document, dict):
        found = type(document).__name__
        raise RuleLoadError(
            f"{path}: a rule file is a mapping with `area`, `about` and `rules`, not a {found}"
        )
    try:
        return RuleFile.model_validate(document)
    except ValidationError as error:
        raise RuleLoadError(f"{path}: {_explain(error)}") from error


def _explain(error: ValidationError) -> str:
    """Pydantic's report, rewritten as the constraint an operator has to satisfy.

    One line per violation, each naming the field's path in the file. The default
    rendering leads with the model class, which is a name nothing in ``data/`` uses.
    """
    lines = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"]) or "<file>"
        lines.append(f"{location}: {detail['msg']}")
    return "; ".join(lines)


def load_rules(data_dir: Path | None = None) -> RuleSet:
    """Load and validate every rule file under *data_dir*, or refuse to return.

    Called at startup. Raises ``RuleLoadError`` -- naming the file and the violated
    constraint -- for a missing directory, an empty one, an unreadable or malformed
    file, a schema violation, or an id used by two files.
    """
    directory = DATA_DIR if data_dir is None else data_dir
    if not directory.is_dir():
        raise RuleLoadError(
            f"{directory}: the rule directory does not exist; the engine does not start "
            "without the rules it answers by"
        )
    paths = sorted(path for path in directory.glob(f"*{_SUFFIX}") if path.is_file())
    if not paths:
        raise RuleLoadError(
            f"{directory}: holds no *{_SUFFIX} rule file; an engine with no rules would "
            "answer by conventions nobody can read"
        )

    entries: list[LoadedRule] = []
    origin: dict[str, Path] = {}
    for path in paths:
        for rule in _read_file(path).rules:
            first = origin.get(rule.id)
            if first is not None:
                raise RuleLoadError(
                    f"{path}: {rule.id} is already defined in {first.name}; a rule id "
                    "names exactly one rule, is stable, and is never reused"
                )
            origin[rule.id] = path
            entries.append(LoadedRule(rule=rule, source_file=path))
    return RuleSet(loaded=tuple(sorted(entries, key=lambda entry: entry.id)))


@lru_cache(maxsize=1)
def rules() -> RuleSet:
    """The packaged rule set, loaded once.

    Cached because the files are immutable for the life of the process (a rule change is
    a deploy of new data, per AD-11), and because a reader-affecting constant read on
    every answer must not be a file read on every answer. The cache holds no failure:
    ``lru_cache`` does not memoise a raised exception, so a broken file keeps failing.
    """
    return load_rules()
