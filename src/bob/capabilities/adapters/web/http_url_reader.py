# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=infrastructure

"""HttpUrlReader — read a concrete web page over aiohttp behind a 🔴 SSRF guard.

Realises :class:`bob.domain.ports.UrlReader` (BOB-054). Because Bob himself fetches an
attacker-influenced URL, SSRF is the primary risk; every request runs the guard BEFORE
a socket is opened and re-runs it on every redirect hop. Order of operations:

1. **Scheme** — accept ONLY ``http`` / ``https`` (blocks ``file://``, ``ftp://`` …).
2. **🔴 SSRF guard (pre-connect)** — resolve the host and reject if ANY resolved IP is
   private / loopback / link-local / reserved / multicast / unspecified. This blocks
   ``127.0.0.1``, ``10/8``, ``172.16/12``, ``192.168/16``, the cloud-metadata address
   ``169.254.169.254``, and IPv6 ``::1`` / ``fc00::/7`` / ``fe80::/10``. A blocked host
   raises :class:`SsrfBlockedError` — a distinct type so the caller tells "blocked"
   from a plain network failure (and never retries a block).
3. **Redirects** — MANUAL (``allow_redirects=False``); each ``3xx`` ``Location`` is
   re-validated by the FULL scheme + SSRF guard before it is followed, capped at
   ``max_redirects`` hops (closes redirect-to-internal, narrows DNS-rebinding).
4. **Limits** — a total timeout; a ``text/html`` / ``text/plain`` content-type
   allowlist (never pull a binary); a STREAMED body aborted once ``max_bytes`` is
   exceeded; a fixed User-Agent; no auth headers.
5. **Extraction** — stdlib ``html.parser`` (no new dependency): drop
   ``<script>/<style>/<head>/<noscript>``, collect visible text, collapse whitespace,
   capture ``<title>``, truncate to ``max_chars``.

Every failure/block/wrong-content-type/empty-text case RAISES (:class:`UrlReadError`
or :class:`SsrfBlockedError`) — the caller (.2) owns fault-tolerance; Bob never
confabulates page content.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from urllib.parse import urljoin, urlparse

import aiohttp

from bob.domain.ports import SsrfBlockedError, UrlReadError, WebPage

if TYPE_CHECKING:
    from types import TracebackType

# Re-exported (imported above) so adapters and infra tests keep importing the read
# failure contract from this module; the canonical definitions live in the domain
# (``bob.domain.ports``) so the application can catch them without importing infra.
__all__ = ["HttpUrlReader", "SsrfBlockedError", "UrlReadError"]

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ALLOWED_CONTENT_TYPES = ("text/html", "text/plain")
_SKIP_TAGS = frozenset({"script", "style", "noscript"})
_STREAM_CHUNK_BYTES = 65_536
_HTTP_OK = 200
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_DEFAULT_HTTPS_PORT = 443
_DEFAULT_HTTP_PORT = 80


# --- Injectable transport seam (real = aiohttp; tests supply fakes, no live network) --


@runtime_checkable
class _HttpResponse(Protocol):
    """The slice of an HTTP response the reader consumes (status + headers + body)."""

    @property
    def status(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def iter_chunked(self, size: int) -> AsyncIterator[bytes]: ...


@runtime_checkable
class _ResponseCtx(Protocol):
    """An async context manager yielding one :class:`_HttpResponse`."""

    async def __aenter__(self) -> _HttpResponse: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...


# host, port -> the resolved IP strings the SSRF guard must vet.
type HostResolver = Callable[[str, int], Awaitable[Sequence[str]]]
# url -> an open-response context manager (allow_redirects is always off).
type UrlOpener = Callable[[str], _ResponseCtx]


class HttpUrlReader:
    """Read a web page over aiohttp behind the SSRF guard (realises UrlReader).

    All limits come from the constructor (fed by
    :func:`bob.capabilities.adapters.web.factory.build_url_reader`); nothing is hardcoded.
    ``resolve`` and ``opener`` are injection seams — production leaves them ``None``
    (real DNS + a real aiohttp session), tests supply deterministic fakes.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_bytes: int,
        max_redirects: int,
        max_chars: int,
        user_agent: str,
        resolve: HostResolver | None = None,
        opener: UrlOpener | None = None,
    ) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._max_chars = max_chars
        self._user_agent = user_agent
        self._resolve = resolve or _default_resolve
        self._opener = opener

    async def read(self, url: str) -> WebPage:
        """Fetch ``url`` (SSRF-guarded, redirects re-validated) and extract its text."""
        if self._opener is not None:
            return await self._read_with_opener(url, self._opener)
        headers = {"User-Agent": self._user_agent}
        async with aiohttp.ClientSession(timeout=self._timeout, headers=headers) as session:
            return await self._read_with_opener(url, _AiohttpOpener(session))

    async def _read_with_opener(self, url: str, opener: UrlOpener) -> WebPage:
        current = url
        redirects = 0
        while True:
            self._validate_scheme(current)
            await self._guard_ssrf(current)
            async with opener(current) as response:
                if response.status in _REDIRECT_STATUSES:
                    redirects += 1
                    if redirects > self._max_redirects:
                        raise UrlReadError(f"too many redirects (> {self._max_redirects})")
                    current = _redirect_target(current, response.headers)
                    continue
                return await self._read_page(current, response)

    async def _read_page(self, final_url: str, response: _HttpResponse) -> WebPage:
        if response.status != _HTTP_OK:
            raise UrlReadError(f"HTTP status {response.status}")
        content_type = response.headers.get("Content-Type", "")
        if not _content_type_allowed(content_type):
            raise UrlReadError(f"disallowed content-type: {content_type!r}")
        raw = await _stream_body(response, self._max_bytes)
        html = raw.decode(_charset_of(content_type), errors="replace")
        title, text = _extract_text(html)
        text = text[: self._max_chars]
        if not text:
            raise UrlReadError("no readable text extracted")
        return WebPage(url=final_url, title=title, text=text)

    def _validate_scheme(self, url: str) -> None:
        scheme = urlparse(url).scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise UrlReadError(f"unsupported URL scheme: {scheme!r}")

    async def _guard_ssrf(self, url: str) -> None:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            raise UrlReadError(f"URL has no host: {url!r}")
        port = parsed.port or (
            _DEFAULT_HTTPS_PORT if parsed.scheme == "https" else _DEFAULT_HTTP_PORT
        )
        addresses = await self._resolve(host, port)
        if not addresses:
            raise UrlReadError(f"host did not resolve: {host!r}")
        for address in addresses:
            # 🔴 Fail closed: an unparseable resolved address is untrusted → refuse to
            # connect (block), never let a bare ValueError escape the SSRF contract.
            try:
                ip = _parse_ip(address)
            except ValueError as exc:
                raise SsrfBlockedError(
                    f"unparseable resolved address {address!r} for host {host!r}"
                ) from exc
            if _is_blocked(ip):
                raise SsrfBlockedError(
                    f"blocked non-public address {address} for host {host!r}"
                )
        # NOTE (accepted residual, v1 — see CONTEXT/RFC): this guard resolves the host
        # and aiohttp re-resolves at connect through the SAME getaddrinfo, so the two do
        # not diverge in practice; a TOCTOU/DNS-rebinding window remains theoretically.
        # Full closure (connect-by-resolved-IP) is a documented future upgrade.


class _AiohttpOpener:
    """The production :data:`UrlOpener`: one keyless, redirect-off GET per hop."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    def __call__(self, url: str) -> _ResponseCtx:
        return _AiohttpCtx(self._session, url)


class _AiohttpCtx:
    """Adapt an aiohttp request context to the reader's :class:`_ResponseCtx` seam."""

    def __init__(self, session: aiohttp.ClientSession, url: str) -> None:
        self._request = session.get(url, allow_redirects=False)

    async def __aenter__(self) -> _HttpResponse:
        return _AiohttpResponse(await self._request.__aenter__())

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._request.__aexit__(exc_type, exc, tb)


class _AiohttpResponse:
    """Adapt an aiohttp ``ClientResponse`` to the reader's :class:`_HttpResponse` seam."""

    def __init__(self, response: aiohttp.ClientResponse) -> None:
        self._response = response

    @property
    def status(self) -> int:
        return self._response.status

    @property
    def headers(self) -> Mapping[str, str]:
        return self._response.headers

    def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        return self._response.content.iter_chunked(size)


async def _default_resolve(host: str, port: int) -> list[str]:
    """Resolve ``host`` to its IP strings via the running loop's ``getaddrinfo``."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def _stream_body(response: _HttpResponse, max_bytes: int) -> bytes:
    """Read the body in chunks, aborting the moment it exceeds ``max_bytes``."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.iter_chunked(_STREAM_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise UrlReadError(f"response body exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _redirect_target(current: str, headers: Mapping[str, str]) -> str:
    location = headers.get("Location")
    if not location:
        raise UrlReadError("redirect response without a Location header")
    return urljoin(current, location)


def _content_type_allowed(content_type: str) -> bool:
    essence = content_type.split(";", 1)[0].strip().lower()
    return essence in _ALLOWED_CONTENT_TYPES


def _charset_of(content_type: str) -> str:
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "charset" and value.strip():
            return value.strip().strip('"')
    return "utf-8"


def _parse_ip(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    # Strip an IPv6 zone/scope id (e.g. ``fe80::1%eth0``) before parsing.
    return ipaddress.ip_address(address.split("%", 1)[0])


# Carrier-grade NAT (RFC 6598) — not covered by ``is_private`` on this Python; can
# reach carrier-internal services, so block it explicitly (review .4 minor).
_CGN_NET = ipaddress.ip_network("100.64.0.0/10")


def _is_blocked(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        or (isinstance(address, ipaddress.IPv4Address) and address in _CGN_NET)
    )


def _extract_text(html: str) -> tuple[str, str]:
    """Return ``(title, body_text)`` from ``html`` via the stdlib parser."""
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.title(), parser.text()


class _TextExtractor(HTMLParser):
    """Collect visible text + the ``<title>``, dropping script/style/head/noscript."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._head_depth = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs  # HTMLParser passes attributes we do not need for text extraction.
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag == "head":
            self._head_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "head" and self._head_depth:
            self._head_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._skip_depth or self._head_depth:
            return
        stripped = data.strip()
        if stripped:
            self._text_parts.append(stripped)

    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())

    def text(self) -> str:
        return " ".join(" ".join(self._text_parts).split())
