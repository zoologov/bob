# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""``recall_memory`` — the first real capability: a wrapper over MemoryRecall.

This is the thin skill that lets GUPPI delegate a memory search to Bob's archive
recall. It exercises the capability seam end to end without any new I/O: it holds
only the injected :class:`~bob.domain.ports.MemoryRecall` port and renders its
hits as a compact result. The agentic, vector-backed ``search_memory`` is a later
epic; this is the keyword-archive wrapper that proves the tool-loop.

Construct it with :func:`make_recall_memory_capability`, passing the recall port;
the registry then advertises it to the model and dispatches calls to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.ports import Capability, MemoryRecall, Permission

# Default number of memories to retrieve per recall — enough to ground an answer
# without flooding the model's context with marginal hits.
_DEFAULT_K = 5

# JSON-Schema advertised to the model so it knows the single ``query`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

_DESCRIPTION = (
    "Search Bob's long-term memory for facts and past conversation relevant to a "
    "query. Use this whenever answering needs something Bob was told earlier — a "
    "name, preference, or detail not in the current conversation."
)


class _RecallMemoryCapability:
    """Capability that delegates a query to the MemoryRecall port (GUPPI skill)."""

    def __init__(self, recall: MemoryRecall, *, k: int = _DEFAULT_K) -> None:
        self._recall = recall
        self._k = k

    @property
    def name(self) -> str:
        return "recall_memory"

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
        """Recall memories for ``args['query']`` and return their contents."""
        query = args.get("query")
        if not isinstance(query, str):
            raise ValueError("recall_memory requires a string 'query' argument")
        hits = await self._recall.recall(query, k=self._k)
        return {"results": [str(hit["content"]) for hit in hits]}


def make_recall_memory_capability(recall: MemoryRecall) -> Capability:
    """Build the ``recall_memory`` capability over the given recall port."""
    return _RecallMemoryCapability(recall)
