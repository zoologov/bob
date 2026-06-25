# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""``code_rationale`` — the self-introspection skill that links CODE to its WHY.

The orchestrating capability behind "почему этот код такой?". It reads the
decision trail of a path / area / topic and composes a compact rationale:

1. :meth:`RepoIntrospector.code_history` → :func:`parse_bead_refs` lifts the
   ``[BOB-XXX]`` decision keys the code traces back to (de-duplicated, capped to the
   top-N most recent so the model's context is never flooded);
2. for each key, :meth:`RepoIntrospector.list_tasks` (``bd show`` — the decision +
   its comments) AND a read of the feature-doc "why" files
   (:func:`feature_doc_dir` + ``/PRD.md`` / ``/RFC.md`` / ``/BRIEF.md``) — a missing
   doc is simply skipped;
3. :meth:`RepoIntrospector.architecture_context` gives the structural picture.

These are woven into ONE compact answer. It is honest (US-4): when the history
carries no decision key it returns "история … не зафиксирована" rather than
fabricating a rationale. It is resilient — any single source failing (a doc not
present, the tracker erroring, git returning nothing) degrades gracefully, never
crashes the turn. Privacy lives INSIDE the .1 port: this policy only ever requests
feature-doc paths, so SOUL / ``bob.db`` / ``.env`` / config are never reached. It is
``permission="safe"`` and conversation-only (never on the autonomous allowlist).

Construct it with :func:`make_code_rationale_capability`, passing the introspector
port (modelled on :mod:`bob.application.capabilities.inspect_architecture`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.domain.introspection.code_history import feature_doc_dir, parse_bead_refs

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.ports import Capability, Permission, RepoIntrospector

# JSON-Schema advertised to the model so it knows the single ``query`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

_DESCRIPTION = (
    "Explain WHY a piece of Bob's code is the way it is: pass a repo-relative path, "
    "an area, or a bead key and Bob traces it through git history to the decisions "
    "(bead tickets + PRD/RFC feature docs) and the architecture graph behind it. Use "
    "this to answer 'why was this built this way?' — read-only and privacy-guarded."
)

# Honest empty-result message (US-4): with no decision key in the history Bob says so
# rather than inventing a rationale.
_NOT_FOUND = "История решения для этого участка кода не зафиксирована."

# The "why" docs read per decision key, in order of decreasing authority.
_WHY_DOCS = ("PRD.md", "RFC.md", "BRIEF.md")

# Cap the decision-key fan-out so a path with a long history does not trigger dozens
# of tracker shows + doc reads (top-N most recent; parse_bead_refs is newest-first).
_MAX_BEAD_REFS = 5

# Per-source render budgets — keep the composed rationale compact for the model.
_TASK_MAX_CHARS = 600
_DOC_MAX_CHARS = 500
_ARCH_MAX_CHARS = 600
_DOC_MAX_LINES = 60

# Persona-facing section markers of the composed "почему".
_HEADER = "Почему этот код такой — след решений:"
_DOCS_LABEL = "Документы:"
_ARCH_LABEL = "Архитектура:"


def _truncate(text: str, limit: int) -> str:
    """Return ``text`` trimmed to ``limit`` characters with an ellipsis if cut."""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "…"


class _CodeRationaleCapability:
    """Capability orchestrating the code↔decision "why" over the introspector port."""

    def __init__(self, introspector: RepoIntrospector) -> None:
        self._introspector = introspector

    @property
    def name(self) -> str:
        return "code_rationale"

    @property
    def description(self) -> str:
        return _DESCRIPTION

    @property
    def input_schema(self) -> Mapping[str, object]:
        return _INPUT_SCHEMA

    @property
    def permission(self) -> Permission:
        return "safe"

    async def execute(self, args: Mapping[str, object]) -> object:
        """Compose the "почему" trail for ``args['query']`` (honest when none)."""
        query = args.get("query")
        if not isinstance(query, str):
            raise ValueError("code_rationale requires a string 'query' argument")

        history = await self._safe_history(query)
        keys = parse_bead_refs(history)[:_MAX_BEAD_REFS]
        if not keys:
            return {"rationale": _NOT_FOUND}

        sections = [_HEADER]
        for key in keys:
            sections.append(await self._key_section(key))
        arch = await self._safe_architecture(query)
        if arch:
            sections.append(f"{_ARCH_LABEL}\n{_truncate(arch, _ARCH_MAX_CHARS)}")
        return {"rationale": "\n\n".join(sections)}

    async def _key_section(self, key: str) -> str:
        """Render one decision key: its tracker entry + present feature docs."""
        lines = [f"[{key}]"]
        tasks = await self._safe_tasks(key)
        if tasks:
            lines.append(_truncate(tasks, _TASK_MAX_CHARS))
        docs = await self._read_why_docs(key)
        if docs:
            lines.append(_DOCS_LABEL)
            lines.extend(docs)
        return "\n".join(lines)

    async def _read_why_docs(self, key: str) -> list[str]:
        """Read the present PRD/RFC/BRIEF for ``key`` (missing ones skipped)."""
        base = feature_doc_dir(key)
        rendered: list[str] = []
        for doc in _WHY_DOCS:
            text = await self._safe_read(f"{base}/{doc}")
            if text:
                rendered.append(f"- {doc}: {_truncate(text, _DOC_MAX_CHARS)}")
        return rendered

    async def _safe_history(self, query: str) -> str:
        try:
            return await self._introspector.code_history(query)
        except Exception:
            return ""

    async def _safe_tasks(self, key: str) -> str:
        try:
            return (await self._introspector.list_tasks(key)).strip()
        except Exception:
            return ""

    async def _safe_read(self, path: str) -> str:
        try:
            return (await self._introspector.read_file(path, max_lines=_DOC_MAX_LINES)).strip()
        except Exception:
            return ""

    async def _safe_architecture(self, query: str) -> str:
        try:
            return (await self._introspector.architecture_context(query)).strip()
        except Exception:
            return ""


def make_code_rationale_capability(introspector: RepoIntrospector) -> Capability:
    """Build the ``code_rationale`` capability over the given introspector port."""
    return _CodeRationaleCapability(introspector)
