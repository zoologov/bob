# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Privilege-judgment seam — value-типы, порт, чистый промпт + парсер (BOB-052 .1).

На сообщение НЕ-авторизованного участника Боб семантически решает (Tier-0, в духе
``ResponseJudge`` BOB-049), нужна ли привилегия. Этот модуль задаёт форму того
решения и шов, через который оно делается, плюс его модель-обращённую (чистую)
половину:

* :class:`PrivilegeNeed` — immutable исход: ``needs_permission`` + ``kind``
  (tool | internal | owner_data) + ``what`` (человекочитаемо, что просят).
* :class:`PrivilegeContext` — immutable ВХОД: текст запроса + подсказки доступных
  capability + лёгкий контекст (recent thread). Подсказки — сигналы, не правила.
* :class:`PrivilegeJudge` — инжектируемый порт: ``assess(ctx) -> PrivilegeNeed``.
  Tier-0 LLM-реализация живёт в infrastructure; тесты инжектят фейк.
* :func:`build_privilege_user_prompt` — чисто сворачивает ``PrivilegeContext`` в
  Tier-0 user-prompt; :data:`PRIVILEGE_JUDGE_SYSTEM_PROMPT` задаёт задачу и
  размеченный выходной контракт.
* :func:`parse_privilege_need` — чисто мапит ответ модели в :class:`PrivilegeNeed`,
  RAISE-ит :class:`PrivilegeJudgeParseError` на мусор (а не тихий дефолт), чтобы
  каллер в .3 декоративно опустил add-on с безопасным дефолтом (= отказ).

🔴 Консервативно: обычная болтовня / общее знание (BOB-051 — память публична) →
``needs_permission=False`` (обычный ответ). Только запрос, которому нужен инструмент /
внутрянка / owner-данные → ``True``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "PRIVILEGE_JUDGE_SYSTEM_PROMPT",
    "PRIVILEGE_KINDS",
    "PrivilegeContext",
    "PrivilegeJudge",
    "PrivilegeJudgeParseError",
    "PrivilegeNeed",
    "build_privilege_user_prompt",
    "parse_privilege_need",
]

# The three privileged kinds the judge may name — the only valid ``kind`` values on a
# privileged need. Keeps the parser conservative: an unknown kind is a real failure.
PRIVILEGE_KINDS: frozenset[str] = frozenset({"tool", "internal", "owner_data"})

# Labelled-line prefixes the parser recognises (case-insensitive, whitespace-tolerant).
_NEEDS_LABEL = re.compile(r"^\s*needs_permission\s*:\s*(.+)$", re.IGNORECASE)
_KIND_LABEL = re.compile(r"^\s*kind\s*:\s*(.+)$", re.IGNORECASE)
_WHAT_LABEL = re.compile(r"^\s*what\s*:\s*(.+)$", re.IGNORECASE)

# Affirmative tokens for the boolean ``needs_permission`` field.
_YES_TOKENS: frozenset[str] = frozenset({"yes", "true", "y", "да"})
_NO_TOKENS: frozenset[str] = frozenset({"no", "false", "n", "нет"})

# Punctuation trimmed off a scanned token before matching.
_WORD_TRIM = " \t\n.!?,:;'\"*-"

PRIVILEGE_JUDGE_SYSTEM_PROMPT = (
    "You are Bob deciding whether ONE message from a NOT-yet-authorised person asks "
    "for something privileged that you must check with your owner first. Privileged "
    "means it needs one of:\n"
    "- tool: running a capability/tool on the person's behalf;\n"
    "- internal: revealing your private inner life / internal notes;\n"
    "- owner_data: disclosing the owner's private data.\n"
    "Be CONSERVATIVE: ordinary conversation, small talk, and general knowledge are "
    "NOT privileged (your shared memory is public) — answer no. Only a request that "
    "genuinely needs a tool, internal info, or owner data is privileged.\n"
    "Reply in exactly this labelled format, nothing else:\n"
    "needs_permission: <yes|no>\n"
    "kind: <tool|internal|owner_data, only when needs_permission is yes>\n"
    "what: <a short human-readable phrase of what is being asked, when yes>"
)


class PrivilegeJudgeParseError(ValueError):
    """Raised when the model's reply cannot be parsed into a :class:`PrivilegeNeed`.

    A real failure signal (not a silent default): the infrastructure judge lets it
    propagate so .3's decorative fault-tolerance drops the add-on with the safe
    default (= refuse) — Bob never grants a privilege from garbage.
    """


@dataclass(frozen=True, slots=True)
class PrivilegeNeed:
    """The immutable outcome of one privilege judgment.

    ``needs_permission`` is the gate: when ``False`` the flow does nothing and Bob
    answers normally. When ``True``, ``kind`` is one of :data:`PRIVILEGE_KINDS` and
    ``what`` is a short human-readable phrase used in the owner notice
    («показать задачи проекта»).
    """

    needs_permission: bool
    kind: str
    what: str


@dataclass(frozen=True, slots=True)
class PrivilegeContext:
    """The immutable input to a privilege judgment (request + hints, not rules).

    ``request_text`` is the not-yet-authorised person's message. ``capability_hints``
    are the names of available capabilities/tools — signals the judge weighs, never a
    map it is bound to. ``recent_thread`` is a light per-person snippet for context;
    it may be empty.
    """

    request_text: str
    capability_hints: Sequence[str]
    recent_thread: str


@runtime_checkable
class PrivilegeJudge(Protocol):
    """The seam: decide, by meaning, whether a request needs owner permission.

    Injectable so the decision is deterministic in tests (a fake returns a scripted
    :class:`PrivilegeNeed`) and swappable in tier without touching any consumer.
    """

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:
        """Weigh ``ctx`` and return the :class:`PrivilegeNeed`."""
        ...


def build_privilege_user_prompt(ctx: PrivilegeContext) -> str:
    """Fold ``ctx`` into the Tier-0 user prompt (pure).

    Includes the request text, the available-capability hints (signals only) and the
    recent per-person thread for light context.
    """
    hints = ", ".join(ctx.capability_hints) if ctx.capability_hints else "(none)"
    lines = [
        "Available capabilities (hints, NOT a map you are bound to):",
        f"  {hints}",
        "",
        "Recent thread with this person:",
        ctx.recent_thread or "  (none)",
        "",
        "Incoming request:",
        ctx.request_text,
    ]
    return "\n".join(lines)


def parse_privilege_need(raw: str) -> PrivilegeNeed:
    """Parse the model's reply into a :class:`PrivilegeNeed` (robust, no defaulting).

    Reads the labelled format (``needs_permission:`` / ``kind:`` / ``what:``).
    ``needs_permission`` must resolve to a clear yes/no — an unrecognisable value
    raises. On a privileged (``yes``) need ``kind`` must be one of
    :data:`PRIVILEGE_KINDS`, otherwise raises (conservative: no usable kind is not a
    safe parse). On ``no`` the kind/what are ignored and a non-privileged need is
    returned.
    """
    needs_text, kind_text, what_text = _scan_labels(raw)
    needs = _parse_bool(needs_text)
    if needs is None:
        raise PrivilegeJudgeParseError(f"no recognisable needs_permission in: {raw!r}")
    if not needs:
        return PrivilegeNeed(needs_permission=False, kind="", what="")
    kind = (kind_text or "").strip().casefold()
    if kind not in PRIVILEGE_KINDS:
        raise PrivilegeJudgeParseError(f"unknown or missing privileged kind: {kind!r}")
    return PrivilegeNeed(needs_permission=True, kind=kind, what=(what_text or "").strip())


def _scan_labels(raw: str) -> tuple[str | None, str | None, str | None]:
    """Extract the needs/kind/what label values from ``raw`` (any may be None)."""
    needs_text: str | None = None
    kind_text: str | None = None
    what_text: str | None = None
    for line in raw.splitlines():
        if needs_text is None and (m := _NEEDS_LABEL.match(line)):
            needs_text = m.group(1)
        elif kind_text is None and (m := _KIND_LABEL.match(line)):
            kind_text = m.group(1)
        elif what_text is None and (m := _WHAT_LABEL.match(line)):
            what_text = m.group(1)
    return needs_text, kind_text, what_text


def _parse_bool(text: str | None) -> bool | None:
    """Resolve a yes/no label value to a bool, or ``None`` when unrecognisable."""
    if text is None:
        return None
    for token in text.split():
        word = token.strip(_WORD_TRIM).casefold()
        if word in _YES_TOKENS:
            return True
        if word in _NO_TOKENS:
            return False
    return None
