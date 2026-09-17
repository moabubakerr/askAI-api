"""The versioned prompt files, and the digest check that makes them immutable.

Purity: IO -- it reads a packaged file, once, and verifies it.

AD-29: *"Every prompt is a versioned file in the repository, immutable once published: a
change is a new version, never an edit... Every answer records ``prompt_id@version`` and
its hash... A missing or altered prompt fails loudly at startup; it never falls back to
another."*

Three of those clauses are structural here rather than remembered.

**Versioned, as the filename.** ``candidate-tie-break.v1.md`` is named for its id and its
version, so version 2 arrives *beside* version 1 instead of on top of it, and a rollback
is the one-word data edit AD-29 says it should be -- ``version`` in
``rules/data/model-tie-break.yaml`` -- rather than a revert.

**Immutable, as a digest.** A file cannot enforce its own immutability; a digest recorded
somewhere a reviewer reads can. The sha256 lives in the rule, the file lives here, and
neither is believed without the other. Editing the published file in place is exactly
what this catches, and it is the only way "immutable" is more than an instruction in a
comment.

**Loudly, as an exception.** ``PromptError`` is raised and never caught in this package.
Every *other* failure on this rung -- an outage, a timeout, output the validator rejected
-- degrades to asking the reader, and that asymmetry is the point: those are facts about
a runtime we do not control, while a prompt that is missing or has been altered is a fact
about *this deployment* and about what the engine is telling a model to do. Degrading
past it would mean answering with a prompt nobody reviewed.

The digest is taken over the file's **text**, decoded as UTF-8 and read with universal
newlines, not over its bytes. A checkout that rewrites line endings -- which is the
default on Windows, where this is developed -- must not read as a tampered prompt, while
a single changed word still must.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Final

from askai.observability.record import PromptUse
from askai.rules import rules

__all__ = [
    "PROMPT_DIR",
    "PromptClause",
    "PromptError",
    "PromptRule",
    "VersionedPrompt",
    "load_prompt",
    "tie_break_prompt",
    "verify_prompts",
]

#: Where the published prompt files live. Beside this module rather than in a top-level
#: directory, because a prompt is part of the adapter that sends it: nothing outside
#: ``adapters/model/`` speaks the protocol, and nothing outside it should be able to
#: reach the text either.
PROMPT_DIR: Final = Path(__file__).parent / "prompts"

#: The extension every published prompt carries. One extension, so a directory listing
#: is the complete inventory and a stray ``.txt`` beside a ``.md`` cannot be "the other
#: copy someone was editing".
_SUFFIX: Final = ".md"


class PromptRule(StrEnum):
    """The rules that declare a published prompt, one per prompt.

    Closed, and iterated by :func:`verify_prompts`, so a prompt added without a rule has
    nowhere to be declared and a rule added without a file fails at startup. AD-22 bounds
    the model to four call sites; this enum grows at most that far.
    """

    TIE_BREAK = "R-MODEL-TIE-BREAK-PROMPT"


class PromptClause(StrEnum):
    """The clauses a prompt rule carries."""

    PROMPT_ID = "prompt_id"
    VERSION = "version"
    SHA256 = "sha256"


class PromptError(RuntimeError):
    """A published prompt is missing, unreadable, empty, or is not the reviewed one.

    Raised, never degraded. See this module's docstring for why this one failure is
    different from every other failure on the model rung.
    """


@dataclass(frozen=True, slots=True)
class VersionedPrompt:
    """One published prompt, verified, with the three things AD-16 records about it.

    Carries its own ``PromptUse`` rather than leaving the answer path to assemble one
    from three loose strings: the record and the text sent are then one statement, and a
    prompt whose recorded hash did not match what was sent is unrepresentable.
    """

    prompt_id: str
    version: str
    prompt_hash: str
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise PromptError(
                f"{self.identity} is empty; an empty instruction is a call with no closed "
                "domain to select from, which is the one shape ModelCall refuses"
            )

    @property
    def identity(self) -> str:
        """``prompt_id@version`` -- AD-29's traceability key, spelled in one place."""
        return f"{self.prompt_id}@{self.version}"

    @property
    def use(self) -> PromptUse:
        """What goes on the answer record for having used this prompt (AD-16, AD-29)."""
        return PromptUse(
            prompt_id=self.prompt_id, version=self.version, prompt_hash=self.prompt_hash
        )


def _clause(rule: PromptRule, clause: PromptClause) -> str:
    value = rules().value(rule.value, clause.value)
    if not isinstance(value, str) or not value.strip():
        raise PromptError(
            f"{rule.value} clause `{clause.value}` is {value!r}; a prompt is identified by "
            "an id, a version and a digest, all three of them text"
        )
    return value.strip()


def digest_of(text: str) -> str:
    """The sha256 recorded for *text*. One spelling, used to verify and to re-record."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@cache
def load_prompt(rule: PromptRule, directory: Path | None = None) -> VersionedPrompt:
    """The prompt *rule* declares, verified against its reviewed digest, or raise.

    Cached, because the file is immutable for the life of the process and a prompt read
    from disk on every answer is a prompt that can change halfway through a deployment.
    ``cache`` does not memoise a raised exception, so a missing or altered file keeps
    failing rather than failing once and then being absent from the cache's point of view.

    *directory* is injectable for the same reason ``ChatModelSettings.from_env`` takes an
    environment: a test that had to write into the packaged prompt directory to assert
    that tampering is caught would be a test that tampers with the shipped prompt.
    """
    root = PROMPT_DIR if directory is None else directory
    prompt_id = _clause(rule, PromptClause.PROMPT_ID)
    version = _clause(rule, PromptClause.VERSION)
    expected = _clause(rule, PromptClause.SHA256)
    path = root / f"{prompt_id}.v{version}{_SUFFIX}"

    if not path.is_file():
        raise PromptError(
            f"{rule.value} declares {prompt_id}@{version} and {path} does not exist. "
            "A prompt is a versioned file in the repository (AD-29); the engine does not "
            "start against a prompt it cannot read, and it never falls back to another."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PromptError(f"{path} could not be read: {type(error).__name__}: {error}") from error

    found = digest_of(text)
    if found != expected:
        raise PromptError(
            f"{prompt_id}@{version} hashes to {found}, and {rule.value} records {expected}. "
            "A published prompt is immutable: a change is a new version and a new digest, "
            "never an edit. The engine does not start against a prompt nobody reviewed."
        )
    return VersionedPrompt(
        prompt_id=prompt_id, version=version, prompt_hash=found, text=text
    )


def tie_break_prompt(directory: Path | None = None) -> VersionedPrompt:
    """The prompt the candidate tie-break sends (Story 2.6)."""
    return load_prompt(PromptRule.TIE_BREAK, directory)


def verify_prompts(directory: Path | None = None) -> tuple[VersionedPrompt, ...]:
    """Load and verify every declared prompt, or raise naming the first that fails.

    AD-29's *"fails loudly at startup"*. Called from the composition root so a deployment
    with a missing or altered prompt does not start and answer -- rather than discovering
    it on the first question that reaches the model rung, which may be weeks later.
    """
    return tuple(load_prompt(rule, directory) for rule in PromptRule)
