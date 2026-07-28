# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``web_search`` — the grounded web-search capability (BOB-053 .2 + .3).

The thin skill that lets GUPPI search the web for Bob: it delegates a ``query``
to the injected :class:`~bob.domain.ports.WebSearchProvider` (Qwen-native over
the Responses API behind the .1 port) and projects the grounded ``answer`` plus
its ``sources`` (title + url) COMPACTLY into the tool-loop — Bob synthesises the
final reply in his own voice with links. It is read-only
(``permission="safe"``); the privilege gate is by sender (authz/BOB-052), NOT
here — the tool-loop only runs for an authorised sender.

🔴 Fault-tolerance («полный Боб или честный GUPPI-нотис», .3): ``web_search`` is
ESSENTIAL the moment the model chose to search, so a provider failure is RETRIED a
bounded number of times with a short backoff (the BOB-049 essential helper
:func:`~bob.application.reliability.call_with_retry`, the same policy the reply
generation uses) through an INJECTED sleep seam (deterministic in tests). If every
attempt fails, the skill does NOT confabulate and does NOT crash the turn: it
returns an HONEST "couldn't search" notice carrying explicit anti-confabulation
``guidance`` so Bob voices the caveat himself — NEVER an answer from training
presented as if found. An empty/whitespace query is answered honestly WITHOUT
calling the provider; empty ``sources`` on success is valid (a grounded answer with
nothing worth citing) and the answer is still returned.

Construct it with :func:`make_web_search_capability`, passing the provider port;
the registry then advertises it to the model and dispatches calls to it (modelled
on :mod:`bob.capabilities.usecases.inspect_architecture`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bob.application.reliability import call_with_retry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.reliability import Sleep
    from bob.capabilities.ports import Capability, Permission, WebSearchProvider

logger = logging.getLogger(__name__)

# Essential-failure retry policy (mirrors HandleMessage's reply-generation defaults,
# BOB-049 .3): the TOTAL number of tries (one initial call + two retries) and the
# short backoff awaited between them. Tunable per persona via ``search.*`` in app wiring.
_DEFAULT_SEARCH_ATTEMPTS = 3
_DEFAULT_SEARCH_BACKOFF_SECONDS = 0.5

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
    "knowledge is needed; otherwise answer directly. Synthesise the answer in your "
    "own voice and cite the source links — do not paste the raw snippets."
)

# Honest empty-query reply: Bob never invents a search for a blank request.
_EMPTY_QUERY = "Пустой запрос — нечего искать в интернете."

# 🔴 Honest essential-failure notice (.3): when the provider keeps failing after the
# bounded retry, the skill surfaces THIS instead of a confabulated "found" answer. The
# ``answer`` is an explicit "couldn't search" caveat and ``guidance`` steers the model to
# say so honestly in Bob's voice — never to pass training knowledge off as searched. RU
# persona voice (project language); Cyrillic look-alikes intentional.
_SEARCH_FAILED_ANSWER = (
    "Не смог выполнить веб-поиск — сеть или провайдер сейчас недоступны, "  # noqa: RUF001
    "проверить это в интернете не получилось."
)
_SEARCH_FAILED_GUIDANCE = (
    "Скажи честно, что не удалось выполнить поиск в интернете; НЕ выдавай знание "  # noqa: RUF001
    "из памяти или обучения под видом найденного в сети."
)


class _WebSearchCapability:
    """Capability delegating a query to the WebSearchProvider port (read-only)."""

    def __init__(
        self,
        provider: WebSearchProvider,
        *,
        attempts: int = _DEFAULT_SEARCH_ATTEMPTS,
        backoff_seconds: float = _DEFAULT_SEARCH_BACKOFF_SECONDS,
        sleep: Sleep | None = None,
    ) -> None:
        self._provider = provider
        if attempts < 1:
            msg = f"attempts must be >= 1, got {attempts}"
            raise ValueError(msg)
        if backoff_seconds < 0:
            msg = f"backoff_seconds must be non-negative, got {backoff_seconds}"
            raise ValueError(msg)
        self._attempts = attempts
        self._backoff_seconds = backoff_seconds
        self._sleep: Sleep = sleep if sleep is not None else asyncio.sleep

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

        Validates a string ``query`` (mirroring the other read-only skills); a blank
        query is answered honestly without calling the provider. The provider call —
        ESSENTIAL once the model chose to search — is retried a bounded number of times
        with a short backoff (BOB-049 essential policy). 🔴 If every attempt fails, the
        failure is turned into an HONEST "couldn't search" notice (with anti-confabulation
        ``guidance``) rather than propagated or — worse — confabulated into a "found"
        answer from training.
        """
        query = args.get("query")
        if not isinstance(query, str):
            raise ValueError("web_search requires a string 'query' argument")
        if not query.strip():
            return {"answer": _EMPTY_QUERY, "sources": []}
        try:
            result = await call_with_retry(
                lambda: self._provider.search(query),
                attempts=self._attempts,
                backoff_seconds=self._backoff_seconds,
                sleep=self._sleep,
            )
        except Exception:  # essential: ANY persistent failure → honest notice, never confabulation
            logger.warning(
                "web_search provider failed after %d attempt(s); surfacing honest notice",
                self._attempts,
                exc_info=True,
            )
            return {
                "answer": _SEARCH_FAILED_ANSWER,
                "sources": [],
                "guidance": _SEARCH_FAILED_GUIDANCE,
            }
        return {
            "answer": result.answer,
            "sources": [
                {"title": source.title, "url": source.url}
                for source in result.sources
            ],
        }


def make_web_search_capability(
    provider: WebSearchProvider,
    *,
    attempts: int = _DEFAULT_SEARCH_ATTEMPTS,
    backoff_seconds: float = _DEFAULT_SEARCH_BACKOFF_SECONDS,
    sleep: Sleep | None = None,
) -> Capability:
    """Build the ``web_search`` capability over the given provider port.

    The bounded essential-retry policy (``attempts``/``backoff_seconds``) and the
    injectable ``sleep`` seam default to the BOB-049 reply-generation values; the app
    wiring may override them from ``search.*`` config.
    """
    return _WebSearchCapability(
        provider, attempts=attempts, backoff_seconds=backoff_seconds, sleep=sleep
    )
