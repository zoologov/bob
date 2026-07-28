# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""``read_url`` — the concrete-URL page-reading capability (BOB-054 .2).

The twin of ``web_search`` (BOB-053): where ``web_search`` searches the web by
topic, this skill opens ONE concrete URL the conversation already carries and
reads it. It delegates a ``url`` to the injected
:class:`~bob.capabilities.ports.UrlReader` (an SSRF-guarded ``aiohttp`` fetch + stdlib
``html.parser`` extraction behind the .1 port), which returns a
:class:`~bob.capabilities.ports.WebPage` already truncated to its char limit, and
projects it COMPACTLY (``url`` + ``title`` + ``excerpt``) into the tool-loop — Bob
synthesises the final reply in his own voice. It is read-only
(``permission="safe"``); the privilege gate is by sender (authz/BOB-052), NOT
here — the tool-loop only runs for an authorised sender.

🔴 Fault-tolerance (mirrors ``web_search`` .3): ``read_url`` is ESSENTIAL the
moment the model chose to read a link, so a TRANSIENT reader failure is RETRIED a
bounded number of times with a short backoff (the BOB-049 essential helper
:func:`~bob.application.reliability.call_with_retry`) through an INJECTED sleep
seam (deterministic in tests). If every attempt fails, the skill does NOT
confabulate and does NOT crash the turn: it returns an HONEST "couldn't open"
notice carrying explicit anti-confabulation ``guidance`` — NEVER invented page
content. 🔴 IMPORTANT nuance vs ``web_search``: a
:class:`~bob.capabilities.adapters.web.SsrfBlockedError` is DETERMINISTIC (a blocked
internal address) — retrying it is pointless, so it is surfaced as the honest
notice IMMEDIATELY, without consuming the retry budget or awaiting the backoff.
An empty/whitespace url is answered honestly WITHOUT calling the reader.

Construct it with :func:`make_read_url_capability`, passing the reader port; the
registry then advertises it to the model and dispatches calls to it (modelled on
:mod:`bob.capabilities.usecases.web_search`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bob.application.reliability import call_with_retry
from bob.capabilities.ports import SsrfBlockedError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.reliability import Sleep
    from bob.capabilities.ports import Capability, Permission, UrlReader, WebPage

logger = logging.getLogger(__name__)

# Essential-failure retry policy (mirrors ``web_search`` / HandleMessage's reply-generation
# defaults, BOB-049 .3): the TOTAL number of tries (one initial call + two retries) and the
# short backoff awaited between them. Tunable per persona via ``read_url.*`` in app wiring.
_DEFAULT_READ_ATTEMPTS = 3
_DEFAULT_READ_BACKOFF_SECONDS = 0.5

# JSON-Schema advertised to the model so it knows the single ``url`` argument.
_INPUT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {"url": {"type": "string"}},
    "required": ["url"],
}

# Kept tight so the model reaches for it ONLY when the conversation carries a concrete
# link to read — never on every message — and never confuses it with ``web_search``.
_DESCRIPTION = (
    "Открыть и прочитать КОНКРЕТНУЮ веб-страницу по URL (статья, пост, документ) "
    "и ответить по её содержимому. Использовать, когда в разговоре есть ссылка, "
    "которую нужно прочитать. Это НЕ web_search: web_search ищет по теме/запросу, "
    "а read_url открывает уже данный URL. Синтезируй ответ своим голосом по прочитанному "
    "— не вставляй сырой текст страницы."
)

# Honest blank-url reply: Bob never invents a page for a missing link.
_BLANK_URL = "Пустая ссылка — нечего открывать и читать."

# 🔴 Honest essential-failure notice: when the reader cannot open/read the page (a
# persistent transient failure OR a deterministic SSRF block), the skill surfaces THIS
# instead of confabulated content. The ``excerpt`` is an explicit "couldn't open" caveat
# and ``guidance`` steers the model to say so honestly in Bob's voice — never to invent
# what the page said. RU persona voice; Cyrillic look-alikes intentional.
_READ_FAILED_EXCERPT = (
    "Не смог открыть или прочитать эту ссылку — страница недоступна, "
    "закрыта логин-воллом или её нельзя безопасно загрузить."
)
_READ_FAILED_GUIDANCE = (
    "Скажи честно, что не удалось открыть и прочитать ссылку; НЕ выдумывай, "
    "что на этой странице, и не выдавай знание из памяти под видом прочитанного."
)


class _ReadUrlCapability:
    """Capability delegating a url to the UrlReader port (read-only)."""

    def __init__(
        self,
        reader: UrlReader,
        *,
        attempts: int = _DEFAULT_READ_ATTEMPTS,
        backoff_seconds: float = _DEFAULT_READ_BACKOFF_SECONDS,
        sleep: Sleep | None = None,
    ) -> None:
        self._reader = reader
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
        return "read_url"

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
        """Open ``args['url']`` and project its content COMPACTLY (url/title/excerpt).

        Validates a string ``url`` (mirroring the other read-only skills); a blank url is
        answered honestly without calling the reader. The reader call — ESSENTIAL once the
        model chose to read — is retried a bounded number of times with a short backoff
        (BOB-049 essential policy) for TRANSIENT failures, but a deterministic
        :class:`SsrfBlockedError` is NOT retried. 🔴 If reading fails, the failure is
        turned into an HONEST "couldn't open" notice (with anti-confabulation ``guidance``)
        rather than propagated or — worse — confabulated into invented page content.
        """
        url = args.get("url")
        if not isinstance(url, str):
            raise ValueError("read_url requires a string 'url' argument")
        if not url.strip():
            return {"url": "", "title": "", "excerpt": _BLANK_URL}
        try:
            page = await call_with_retry(
                lambda: self._read_transient(url),
                attempts=self._attempts,
                backoff_seconds=self._backoff_seconds,
                sleep=self._sleep,
            )
        except Exception:  # essential: ANY persistent failure → honest notice, never confabulation
            logger.warning(
                "read_url reader failed after %d attempt(s); surfacing honest notice",
                self._attempts,
                exc_info=True,
            )
            return self._failed_notice(url)
        if page is None:
            # 🔴 Deterministic SSRF block — NOT retried (see ``_read_transient``): the
            # reader was called exactly once and the backoff never awaited.
            logger.warning("read_url blocked by SSRF guard; surfacing honest notice")
            return self._failed_notice(url)
        return {"url": page.url, "title": page.title, "excerpt": page.text}

    async def _read_transient(self, url: str) -> WebPage | None:
        """Read ``url``, returning ``None`` (never raising) for a deterministic SSRF block.

        Only TRANSIENT failures propagate as exceptions so ``call_with_retry`` retries
        them; a :class:`SsrfBlockedError` short-circuits to ``None`` so the bounded retry
        gives up at once (a blocked internal address will never resolve differently).
        """
        try:
            return await self._reader.read(url)
        except SsrfBlockedError:
            return None

    def _failed_notice(self, url: str) -> Mapping[str, object]:
        return {
            "url": url,
            "title": "",
            "excerpt": _READ_FAILED_EXCERPT,
            "guidance": _READ_FAILED_GUIDANCE,
        }


def make_read_url_capability(
    reader: UrlReader,
    *,
    attempts: int = _DEFAULT_READ_ATTEMPTS,
    backoff_seconds: float = _DEFAULT_READ_BACKOFF_SECONDS,
    sleep: Sleep | None = None,
) -> Capability:
    """Build the ``read_url`` capability over the given reader port (BOB-054 .2).

    The bounded essential-retry policy (``attempts``/``backoff_seconds``) and the
    injectable ``sleep`` seam default to the BOB-049 reply-generation values; the app
    wiring may override them from ``read_url.*`` config. A deterministic SSRF block is
    never retried (see :meth:`_ReadUrlCapability._read_transient`).
    """
    return _ReadUrlCapability(
        reader, attempts=attempts, backoff_seconds=backoff_seconds, sleep=sleep
    )
