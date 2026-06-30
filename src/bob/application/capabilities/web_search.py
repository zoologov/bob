# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""``web_search`` — the grounded web-search capability (BOB-053 .2).

The thin skill that lets GUPPI search the web for Bob: it delegates a ``query``
to the injected :class:`~bob.domain.ports.WebSearchProvider` (Qwen-native over
the Responses API behind the .1 port) and projects the grounded ``answer`` plus
its ``sources`` (title + url) COMPACTLY into the tool-loop — Bob synthesises the
final reply in his own voice with links. It is read-only
(``permission="safe"``); the privilege gate is by sender (authz/BOB-052), NOT
here — the tool-loop only runs for an authorised sender.

🔴 It never confabulates a "found" answer: a provider failure PROPAGATES (.3
owns fault-tolerance), and an empty/whitespace query is answered honestly
WITHOUT calling the provider. Empty ``sources`` is valid — a grounded answer with
nothing worth citing — and the answer is still returned.

Construct it with :func:`make_web_search_capability`, passing the provider port;
the registry then advertises it to the model and dispatches calls to it (modelled
on :mod:`bob.application.capabilities.inspect_architecture`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.domain.ports import Capability, Permission, WebSearchProvider

# JSON-Schema advertised to the model so it knows the single ``query`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}

# Kept tight so the model only reaches for it on genuinely fresh/external needs —
# not on every message (over-firing risk, see RFC «Гипер-вызов»).
_DESCRIPTION = (
    "Search the web for fresh, external or current information that is NOT in "
    "Bob's memory or training (recent events, today's facts, live data) and "
    "return a grounded answer with sources. Use ONLY when up-to-date or external "
    "knowledge is needed; otherwise answer directly."
)

# Honest empty-query reply: Bob never invents a search for a blank request.
_EMPTY_QUERY = "Пустой запрос — нечего искать в интернете."


class _WebSearchCapability:
    """Capability delegating a query to the WebSearchProvider port (read-only)."""

    def __init__(self, provider: WebSearchProvider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "web_search"

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
        """Search the web for ``args['query']`` and project answer + sources.

        Validates a string ``query`` (mirroring the other read-only skills);
        a blank query is answered honestly without calling the provider. The
        provider's failure is NOT caught here — it propagates so Bob never
        confabulates a "found" answer (.3 owns fault-tolerance).
        """
        query = args.get("query")
        if not isinstance(query, str):
            raise ValueError("web_search requires a string 'query' argument")
        if not query.strip():
            return {"answer": _EMPTY_QUERY, "sources": []}
        result = await self._provider.search(query)
        return {
            "answer": result.answer,
            "sources": [
                {"title": source.title, "url": source.url}
                for source in result.sources
            ],
        }


def make_web_search_capability(provider: WebSearchProvider) -> Capability:
    """Build the ``web_search`` capability over the given provider port."""
    return _WebSearchCapability(provider)
