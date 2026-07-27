# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``search_memory`` — the first agentic capability: Bob searches his own memory.

Where ``recall_memory`` is the thin *auto*-recall (GUPPI quietly grounds an
answer), ``search_memory`` is the skill Bob *chooses* to invoke through the
tool-loop: he decides to search his own long-term archive with a real query,
runs the hybrid semantic+keyword recall over everything he remembers, and uses
the result. This is the first substantive agentic capability on the seam.

It holds only the injected :class:`~bob.domain.ports.MemoryRecall` port (the
hybrid recall) — no I/O of its own — and renders its hits as a compact,
model-friendly result. The model may tune how many memories to pull back via an
optional ``k``; nonsense values clamp to a safe default so a sloppy model cannot
flood or starve its own context. Construct it with
:func:`make_search_memory_capability`, mirroring ``recall_memory``; the registry
then advertises it to the model and dispatches calls to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.ports import Capability, MemoryRecall, Permission

# Default number of memories to pull back per agentic search — a touch wider than
# auto-recall, since an explicit search is meant to dig, without flooding context.
_DEFAULT_K = 8

# Hard ceiling on a model-supplied ``k`` — keeps an over-eager request from
# pulling back a context-flooding wall of marginal hits.
_MAX_K = 50

# JSON-Schema advertised to the model: a required ``query`` plus an optional ``k``
# the model may tune to ask for more or fewer memories.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "What to search Bob's long-term memory for.",
        },
        "k": {
            "type": "integer",
            "description": "How many memories to pull back (optional).",
        },
    },
    "required": ["query"],
}

_DESCRIPTION = (
    "Search my long-term memory for things related to a query — facts and past "
    "conversations across the whole archive (semantic + keyword). Reach for this "
    "whenever the answer needs something Bob may have learned or discussed before "
    "but isn't in the current conversation; pick a focused query, optionally set "
    "'k' for how many memories to pull back."
)


def _resolve_k(raw: object) -> int:
    """Clamp a model-supplied ``k`` into ``[1, _MAX_K]`` (default on nonsense).

    Models emit junk: a missing, non-integer, zero, negative, or huge ``k`` all
    fall back to a sane window rather than reaching the recall port verbatim.
    ``bool`` is rejected explicitly (it is an ``int`` subclass in Python).
    """
    if not isinstance(raw, int) or isinstance(raw, bool):
        return _DEFAULT_K
    if raw <= 0:
        return _DEFAULT_K
    return min(raw, _MAX_K)


class _SearchMemoryCapability:
    """Agentic capability: Bob searches his own memory via the MemoryRecall port."""

    def __init__(self, recall: MemoryRecall) -> None:
        self._recall = recall

    @property
    def name(self) -> str:
        return "search_memory"

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
        """Search memory for ``args['query']`` (optional ``k``) and return hits."""
        query = args.get("query")
        if not isinstance(query, str):
            raise ValueError("search_memory requires a string 'query' argument")
        k = _resolve_k(args.get("k"))
        hits = await self._recall.recall(query, k=k)
        return {"results": [str(hit["content"]) for hit in hits]}


def make_search_memory_capability(recall: MemoryRecall) -> Capability:
    """Build the agentic ``search_memory`` capability over the given recall port."""
    return _SearchMemoryCapability(recall)
