# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=application

"""coding_context — build a bounded, privacy-safe architectural-context preamble.

The light "Bob brings the project's WHY into the coding prompt" helper (BOB-046 .3).
Before Bob hands a task to Claude Code, this composes a SHORT preamble that grounds
the run in the project's own conventions and the task-area architecture, so claude
codes like a partner who knows the rationale — not a smart editor seeing the tree for
the first time. It is built from THREE public sources, in order:

1. the project conventions essentials (stack + DDD/Clean layering + dependency
   direction) — a static, public constant (CLAUDE.md §0.1);
2. the convention docs (``docs/architecture.md`` summary) read through the read-only
   :class:`~bob.capabilities.ports.RepoIntrospector` port;
3. the task-area rationale via :meth:`RepoIntrospector.architecture_context` (the
   ``inspect_architecture`` seam — beadloom ctx/graph/search behind the .1 port).

🔴 Privacy (BOB-034 / BOB-067): every doc path is checked BEFORE it is read against
two policies — the pure
:class:`~bob.capabilities.introspection.privacy_guard.PrivacyGuard` rejects a path
escaping the repo, and coding's OWN narrower safe-doc policy
(:func:`_is_safe_doc_path`) rejects a personal-data doc (``data/soul`` / ``bob.db`` /
``.env`` / ``config`` / ``.claude`` settings). Since BOB-067 the introspection guard
allows the WHOLE repo for in-chat reads, so this narrower curation is what keeps
private material out of the EXTERNAL coder preamble — a denied path is skipped, never
read — and the assembled text is still run through :meth:`PrivacyGuard.sanitize` as a
defence-in-depth backstop. Only public architecture/convention material reaches the
prompt.

🔴 Bounded: each source is char-capped and the whole preamble is truncated to
:data:`PREAMBLE_MAX_CHARS`, so the prompt is never flooded.

It is resilient — any single source failing (a doc not present, the graph returning
nothing) degrades gracefully and never crashes the run; with NO material at all it
returns ``""`` and the caller keeps the unmodified prompt. Construct it with
:func:`make_coding_context`; the composition root injects it into
:class:`~bob.coding.usecases.coding_assistant.CodingAssistant` as an OPTIONAL
dependency (default ``None`` → no preamble), so it is off-by-default-safe and testable
with a deterministic fake introspector.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.capabilities.introspection.privacy_guard import PrivacyGuard
    from bob.coding.usecases.coding_assistant import CodingContext

__all__ = ["PREAMBLE_MAX_CHARS", "make_coding_context"]

# 🔴 The hard ceiling on the whole returned preamble — the prompt is never flooded.
PREAMBLE_MAX_CHARS = 1500

# Per-source render budgets (kept well under the total so a single huge source cannot
# crowd out the others before the final truncation).
_DOC_MAX_CHARS = 700
_DOC_MAX_LINES = 40
_ARCH_MAX_CHARS = 600

# The project conventions essentials — a STATIC, PUBLIC constant (CLAUDE.md §0.1). It
# carries no private material, so it never needs the privacy guard; it just reminds
# claude of Bob's stack and the dependency-direction rules it must respect.
_CONVENTIONS = (
    "Bob v0.1.0 · Python 3.12+ (asyncio) · Telegram (aiogram) · Ollama (Qwen 2.5) · "
    "SQLite+FTS5 · pytest · ruff · mypy --strict. "
    "Архитектура — DDD + Clean Architecture, слои: application/ (use-cases, "
    "GUPPI-рантайм), domain/ (чистое ядро личности и памяти, без I/O), "
    "infrastructure/ (адаптеры Telegram/Ollama/SQLite). Зависимости направлены "
    "внутрь: infrastructure → application → domain; домен остаётся I/O-free. "
    "Стиль — TDD, детерминированные тесты (порты инъектируются), без print/bare except."
)

# The convention docs read for the structural picture — only PUBLIC source/doc
# trees; each is re-checked against the safe-doc policy below before reading.
_CONVENTION_DOCS: tuple[str, ...] = ("docs/architecture.md",)

# Repo-relative roots whose docs are safe to embed in an EXTERNAL coder preamble
# (public source/test/doc trees + the curation-vision + feature specs). This is
# coding's OWN curation policy, DELIBERATELY NARROWER than the introspection
# :class:`PrivacyGuard`, which since BOB-067 allows the WHOLE repo for in-chat reads.
# The coder preamble must never carry personal-data docs (SOUL / ``bob.db`` / ``.env``
# / ``config`` / ``.claude`` settings), so ONLY these roots pass — matched by full
# path-segment prefix so a lookalike sibling (``srcfoo``) never sneaks in.
_SAFE_DOC_ROOT_SEGMENTS: tuple[tuple[str, ...], ...] = (
    ("src",),
    ("tests",),
    ("docs",),
    (".claude", "dev-docs"),
    (".claude", "development", "docs"),
)


def _is_safe_doc_path(path: str) -> bool:
    """Whether ``path`` sits under a root safe to ship to the external coder.

    A pure segment-prefix test against :data:`_SAFE_DOC_ROOT_SEGMENTS`: a personal-data
    doc (SOUL / ``bob.db`` / ``.env`` / ``config`` / ``.claude`` settings) matches no
    safe root and is excluded, so it can never reach the coder preamble even though the
    widened full-repo guard would allow reading it in chat.
    """
    parts = Path(path).parts
    return any(
        len(parts) >= len(root) and parts[: len(root)] == root
        for root in _SAFE_DOC_ROOT_SEGMENTS
    )

# Persona-facing framing so claude reads the block as project context, not the task.
_HEADER = (
    "# Контекст проекта (учитывай конвенции и архитектуру Боба при планировании "
    "и правках):"
)
_ARCH_LABEL = "Архитектура области задачи:"


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` trimmed to at most ``limit`` chars, with an ellipsis if cut."""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 1].rstrip() + "…"


class _ContextIntrospector(Protocol):
    """The narrow read-only surface the builder needs (ISP slice of RepoIntrospector).

    Both methods are guard-enforced inside their implementation; the builder depends
    only on these two so a test fake stays tiny and :class:`RepoIntrospector`
    structurally satisfies it in the composition root.
    """

    async def read_file(self, path: str, *, max_lines: int) -> str:
        """Return up to ``max_lines`` of ``path`` (guard-checked inside the port)."""
        ...

    async def architecture_context(self, ref: str) -> str:
        """Return grounded architecture context for ``ref`` (read-only, public)."""
        ...


@dataclass(frozen=True, slots=True)
class _CodingContextBuilder:
    """Compose a bounded, privacy-safe architectural-context preamble for a task."""

    introspector: _ContextIntrospector
    guard: PrivacyGuard
    doc_paths: tuple[str, ...]
    max_chars: int
    conventions: str = _CONVENTIONS

    async def preamble(self, task: str) -> str:
        """Build the preamble for ``task`` (``""`` when no material is available).

        Conventions + guard-allowed convention docs + the task-area rationale are
        joined, framed, sanitised and truncated to :attr:`max_chars`. Any empty/denied
        source is simply omitted; with nothing to add the result is ``""`` so the
        caller keeps the unmodified prompt.
        """
        sections: list[str] = [self.conventions.strip()]
        for path in self.doc_paths:
            section = await self._doc_section(path)
            if section:
                sections.append(section)
        arch = await self._safe_architecture(task)
        if arch:
            sections.append(f"{_ARCH_LABEL}\n{_truncate(arch, _ARCH_MAX_CHARS)}")
        body = "\n\n".join(section for section in sections if section.strip())
        if not body.strip():
            return ""
        framed = self.guard.sanitize(f"{_HEADER}\n\n{body}")
        return _truncate(framed, self.max_chars)

    async def _doc_section(self, path: str) -> str:
        """Render one convention doc — ONLY a safe, in-repo doc is read.

        🔴 Two checks happen BEFORE any read: the guard rejects a path escaping the
        repo, and the coding-specific safe-doc policy rejects a personal-data doc
        (SOUL / ``bob.db`` / ``.env`` / config / ``.claude`` settings). Since BOB-067
        the introspection guard allows the whole repo for in-chat reads, so this
        NARROWER curation policy is what keeps private material out of the EXTERNAL
        coder preamble — a denied doc is never even requested.
        """
        if not self.guard.allows_path(Path(path)) or not _is_safe_doc_path(path):
            return ""
        text = await self._safe_read(path)
        if not text:
            return ""
        return f"{path}:\n{_truncate(text, _DOC_MAX_CHARS)}"

    async def _safe_read(self, path: str) -> str:
        """Read ``path`` through the port, degrading to ``""`` on any failure."""
        try:
            text = await self.introspector.read_file(path, max_lines=_DOC_MAX_LINES)
        except Exception:
            return ""
        return text.strip()

    async def _safe_architecture(self, ref: str) -> str:
        """Fetch task-area architecture context, degrading to ``""`` on any failure."""
        try:
            context = await self.introspector.architecture_context(ref)
        except Exception:
            return ""
        return context.strip()


def make_coding_context(
    introspector: _ContextIntrospector,
    guard: PrivacyGuard,
    *,
    doc_paths: Sequence[str] = _CONVENTION_DOCS,
    max_chars: int = PREAMBLE_MAX_CHARS,
) -> CodingContext:
    """Build the architectural-context preamble source over the introspector + guard.

    ``doc_paths`` and ``max_chars`` are injectable so the convention docs and the
    budget can be tuned (and a test can target the privacy/bound behaviour directly).
    """
    return _CodingContextBuilder(
        introspector=introspector,
        guard=guard,
        doc_paths=tuple(doc_paths),
        max_chars=max_chars,
    )
