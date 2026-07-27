# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for HttpUrlReader — the 🔴 SSRF guard, redirects, limits, extraction (BOB-054).

No live network: DNS is a deterministic fake resolver (host -> IP strings the guard
vets) and HTTP is a fake opener yielding canned responses. Every blocked-address class
is asserted individually, redirects are re-validated per hop, and the stdlib
``html.parser`` extraction is exercised directly.
"""

from __future__ import annotations

import asyncio
import socket
from typing import TYPE_CHECKING

import aiohttp
import pytest

from bob.capabilities.adapters.web.http_url_reader import (
    HttpUrlReader,
    SsrfBlockedError,
    UrlReadError,
    _default_resolve,
    _extract_text,
    _stream_body,
)
from bob.domain.ports import UrlReader, WebPage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from bob.capabilities.adapters.web.http_url_reader import (
        HostResolver,
        UrlOpener,
        _ResponseCtx,
    )

_PUBLIC_IP = "93.184.216.34"


class _FakeResponse:
    """Doubles as the HTTP response AND its async context manager (one open)."""

    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        chunks: Sequence[bytes] = (),
    ) -> None:
        self.status = status
        self._headers = headers or {}
        self._chunks = list(chunks)

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _html_response(html: str, *, content_type: str = "text/html; charset=utf-8") -> _FakeResponse:
    return _FakeResponse(headers={"Content-Type": content_type}, chunks=[html.encode()])


def _redirect_response(location: str, *, status: int = 302) -> _FakeResponse:
    return _FakeResponse(status=status, headers={"Location": location})


def _resolver(mapping: dict[str, Sequence[str]]) -> HostResolver:
    async def resolve(host: str, _port: int) -> Sequence[str]:
        return list(mapping.get(host, [_PUBLIC_IP]))

    return resolve


def _opener(routes: Mapping[str, _FakeResponse | _ExplodingBodyResponse]) -> UrlOpener:
    def opener(url: str) -> _ResponseCtx:
        if url not in routes:
            raise AssertionError(f"unexpected fetch of {url!r}")
        return routes[url]

    return opener


def _reader(
    *,
    resolve: HostResolver,
    opener: UrlOpener,
    max_bytes: int = 2_000_000,
    max_redirects: int = 5,
    max_chars: int = 10_000,
) -> HttpUrlReader:
    return HttpUrlReader(
        timeout_seconds=15.0,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        max_chars=max_chars,
        user_agent="test-ua",
        resolve=resolve,
        opener=opener,
    )


def test_http_url_reader_is_a_url_reader() -> None:
    reader = _reader(resolve=_resolver({}), opener=_opener({}))
    assert isinstance(reader, UrlReader)


def test_ssrf_error_is_a_url_read_error() -> None:
    assert issubclass(SsrfBlockedError, UrlReadError)


@pytest.mark.parametrize("scheme_url", ["file:///etc/passwd", "ftp://host/x", "gopher://h/"])
async def test_rejects_non_http_schemes(scheme_url: str) -> None:
    reader = _reader(resolve=_resolver({}), opener=_opener({}))
    with pytest.raises(UrlReadError, match="scheme"):
        await reader.read(scheme_url)


@pytest.mark.parametrize(
    "blocked_ip",
    [
        "127.0.0.1",  # IPv4 loopback
        "::1",  # IPv6 loopback
        "10.0.0.5",  # RFC1918 private
        "192.168.1.1",  # RFC1918 private
        "172.16.9.9",  # RFC1918 private
        "169.254.169.254",  # link-local — cloud metadata
        "fe80::1",  # IPv6 link-local
        "fc00::1",  # IPv6 ULA (fc00::/7)
        "0.0.0.0",  # noqa: S104 — unspecified (a blocked test address, not a bind)
        "224.0.0.1",  # multicast
    ],
)
async def test_ssrf_guard_blocks_non_public_addresses(blocked_ip: str) -> None:
    reader = _reader(resolve=_resolver({"evil.test": [blocked_ip]}), opener=_opener({}))
    with pytest.raises(SsrfBlockedError):
        await reader.read("http://evil.test/path")


async def test_ssrf_guard_blocks_when_any_resolved_ip_is_private() -> None:
    # A public + a private answer for the same host must still be blocked.
    reader = _reader(
        resolve=_resolver({"mixed.test": [_PUBLIC_IP, "10.1.2.3"]}), opener=_opener({})
    )
    with pytest.raises(SsrfBlockedError):
        await reader.read("http://mixed.test/")


async def test_reads_public_html_page_happy_path() -> None:
    html = (
        "<html><head><title>Hello Title</title></head>"
        "<body><p>Body words here.</p></body></html>"
    )
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/article": _html_response(html)}),
    )

    page = await reader.read("http://public.test/article")

    assert isinstance(page, WebPage)
    assert page.url == "http://public.test/article"
    assert page.title == "Hello Title"
    assert page.text == "Body words here."


async def test_redirect_to_internal_is_blocked_on_second_hop() -> None:
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP], "internal.test": ["10.0.0.1"]}),
        opener=_opener(
            {"http://public.test/": _redirect_response("http://internal.test/secret")}
        ),
    )
    with pytest.raises(SsrfBlockedError):
        await reader.read("http://public.test/")


async def test_follows_public_redirect_and_reports_final_url() -> None:
    html = "<html><head><title>Final</title></head><body>Landed here.</body></html>"
    reader = _reader(
        resolve=_resolver({"a.test": [_PUBLIC_IP], "b.test": [_PUBLIC_IP]}),
        opener=_opener(
            {
                "http://a.test/start": _redirect_response("http://b.test/end"),
                "http://b.test/end": _html_response(html),
            }
        ),
    )

    page = await reader.read("http://a.test/start")

    assert page.url == "http://b.test/end"
    assert page.title == "Final"
    assert page.text == "Landed here."


async def test_too_many_redirects_raises() -> None:
    routes = {
        "http://a.test/1": _redirect_response("http://a.test/2"),
        "http://a.test/2": _redirect_response("http://a.test/3"),
    }
    reader = _reader(
        resolve=_resolver({"a.test": [_PUBLIC_IP]}),
        opener=_opener(routes),
        max_redirects=1,
    )
    with pytest.raises(UrlReadError, match="redirect"):
        await reader.read("http://a.test/1")


async def test_rejects_disallowed_content_type() -> None:
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener(
            {
                "http://public.test/file.pdf": _FakeResponse(
                    headers={"Content-Type": "application/pdf"}, chunks=[b"%PDF-1.7"]
                )
            }
        ),
    )
    with pytest.raises(UrlReadError, match="content-type"):
        await reader.read("http://public.test/file.pdf")


async def test_rejects_non_ok_status() -> None:
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener(
            {
                "http://public.test/x": _FakeResponse(
                    status=404, headers={"Content-Type": "text/html"}
                )
            }
        ),
    )
    with pytest.raises(UrlReadError, match="status"):
        await reader.read("http://public.test/x")


async def test_empty_extracted_text_raises() -> None:
    html = (
        "<html><head><title>Only title</title></head>"
        "<body><script>var x=1;</script></body></html>"
    )
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/": _html_response(html)}),
    )
    with pytest.raises(UrlReadError, match="text"):
        await reader.read("http://public.test/")


async def test_text_is_truncated_to_max_chars() -> None:
    html = "<html><body>" + ("a" * 500) + "</body></html>"
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/": _html_response(html)}),
        max_chars=100,
    )

    page = await reader.read("http://public.test/")

    assert len(page.text) == 100


async def test_stream_body_aborts_once_max_bytes_exceeded() -> None:
    response = _FakeResponse(chunks=[b"x" * 40, b"y" * 40, b"z" * 40])
    with pytest.raises(UrlReadError, match="bytes"):
        await _stream_body(response, max_bytes=50)


async def test_stream_body_returns_full_body_within_limit() -> None:
    response = _FakeResponse(chunks=[b"ab", b"cd"])
    body = await _stream_body(response, max_bytes=10)
    assert body == b"abcd"


def test_extract_text_strips_script_style_head_noscript() -> None:
    html = (
        "<html><head><title>T</title><style>.a{color:red}</style></head>"
        "<body><script>alert(1)</script><noscript>fallback</noscript>"
        "<p>Visible one</p><p>Visible two</p></body></html>"
    )
    title, text = _extract_text(html)
    assert title == "T"
    assert text == "Visible one Visible two"
    assert "alert" not in text
    assert "color:red" not in text
    assert "fallback" not in text


def test_extract_text_collapses_whitespace() -> None:
    html = "<body>   lots\n\tof   space   </body>"
    _title, text = _extract_text(html)
    assert text == "lots of space"


async def test_uses_declared_charset_to_decode_body() -> None:
    html = "<html><body>café</body></html>"
    encoded = html.encode("latin-1")
    response = _FakeResponse(
        headers={"Content-Type": "text/plain; charset=latin-1"}, chunks=[encoded]
    )
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/": response}),
    )

    page = await reader.read("http://public.test/")

    assert "café" in page.text


# --- .3 hardening: SSRF no-connect locks + extra classes + resolve/host edges ----------


class _RecordingOpener:
    """A :data:`UrlOpener` recording every url it is asked to open.

    The SSRF invariant is not just "block" — it is "block BEFORE a socket is opened".
    A recording opener lets a test assert the guard short-circuits with an EMPTY open
    log (nothing fetched) or, for a redirect, that ONLY the public first hop was opened.
    """

    def __init__(self, routes: dict[str, _FakeResponse] | None = None) -> None:
        self._routes = routes or {}
        self.opened: list[str] = []

    def __call__(self, url: str) -> _ResponseCtx:
        self.opened.append(url)
        if url not in self._routes:
            raise AssertionError(f"unexpected fetch of {url!r}")
        return self._routes[url]


class _ExplodingBodyResponse:
    """A 200 response whose body raises if iterated — proves a rejected type pulls none."""

    def __init__(self, *, headers: dict[str, str]) -> None:
        self.status = 200
        self._headers = headers

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
        raise AssertionError("body must not be pulled for a rejected content-type")

    async def __aenter__(self) -> _ExplodingBodyResponse:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.parametrize(
    "blocked_ip",
    [
        "::",  # IPv6 unspecified (the ``0.0.0.0`` twin)
        "fd00::1",  # IPv6 ULA — the fd00::/8 half of fc00::/7
        "fe80::",  # IPv6 link-local, all-zero interface id
    ],
)
async def test_ssrf_guard_blocks_additional_ipv6_classes(blocked_ip: str) -> None:
    reader = _reader(resolve=_resolver({"evil.test": [blocked_ip]}), opener=_opener({}))
    with pytest.raises(SsrfBlockedError):
        await reader.read("http://evil.test/path")


async def test_ssrf_block_opens_no_http_connection() -> None:
    # 🔴 The guard must reject BEFORE any socket is opened — the opener sees nothing.
    opener = _RecordingOpener()
    reader = _reader(resolve=_resolver({"evil.test": ["10.0.0.1"]}), opener=opener)

    with pytest.raises(SsrfBlockedError):
        await reader.read("http://evil.test/x")

    assert opener.opened == []


async def test_mixed_public_and_private_answers_open_no_connection() -> None:
    # No partial trust: a public+private DNS answer set is blocked with nothing fetched.
    opener = _RecordingOpener()
    reader = _reader(
        resolve=_resolver({"mixed.test": [_PUBLIC_IP, "192.168.0.9"]}), opener=opener
    )

    with pytest.raises(SsrfBlockedError):
        await reader.read("http://mixed.test/")

    assert opener.opened == []


async def test_raises_when_host_does_not_resolve() -> None:
    opener = _RecordingOpener()
    reader = _reader(resolve=_resolver({"ghost.test": []}), opener=opener)

    with pytest.raises(UrlReadError, match="resolve"):
        await reader.read("http://ghost.test/")

    assert opener.opened == []  # nothing fetched for an unresolvable host


async def test_raises_when_url_has_no_host() -> None:
    reader = _reader(resolve=_resolver({}), opener=_opener({}))
    with pytest.raises(UrlReadError, match="host"):
        await reader.read("http:///only-a-path")


async def test_ip_literal_host_is_still_guarded() -> None:
    # A raw-IP URL is not special-cased: getaddrinfo echoes the literal and the guard
    # blocks it exactly like a hostname that resolves there.
    reader = _reader(resolve=_resolver({"127.0.0.1": ["127.0.0.1"]}), opener=_opener({}))
    with pytest.raises(SsrfBlockedError):
        await reader.read("http://127.0.0.1/admin")


# --- .3 hardening: redirect re-validation edges ----------------------------------------


async def test_redirect_scheme_downgrade_to_non_http_is_blocked() -> None:
    # A 3xx to a non-http(s) target is re-validated and rejected on the second hop.
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/": _redirect_response("ftp://public.test/x")}),
    )
    with pytest.raises(UrlReadError, match="scheme"):
        await reader.read("http://public.test/")


async def test_redirect_without_location_header_raises() -> None:
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/": _FakeResponse(status=302, headers={})}),
    )
    with pytest.raises(UrlReadError, match="Location"):
        await reader.read("http://public.test/")


@pytest.mark.parametrize("internal_ip", ["169.254.169.254", "::1", "127.0.0.1"])
async def test_redirect_to_internal_is_blocked_and_internal_never_fetched(
    internal_ip: str,
) -> None:
    # 🔴 Second-hop re-validation blocks the internal target AND never opens it — the
    # only fetch is the public first hop.
    opener = _RecordingOpener(
        {"http://public.test/": _redirect_response("http://internal.test/secret")}
    )
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP], "internal.test": [internal_ip]}),
        opener=opener,
    )

    with pytest.raises(SsrfBlockedError):
        await reader.read("http://public.test/")

    assert opener.opened == ["http://public.test/"]


# --- .3 hardening: reader limits + content-type edges ----------------------------------


async def test_read_aborts_end_to_end_when_body_exceeds_max_bytes() -> None:
    big = "<html><body>" + ("x" * 500) + "</body></html>"
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/": _html_response(big)}),
        max_bytes=100,
    )
    with pytest.raises(UrlReadError, match="bytes"):
        await reader.read("http://public.test/")


async def test_disallowed_content_type_pulls_no_body() -> None:
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener(
            {
                "http://public.test/f": _ExplodingBodyResponse(
                    headers={"Content-Type": "application/octet-stream"}
                )
            }
        ),
    )
    with pytest.raises(UrlReadError, match="content-type"):
        await reader.read("http://public.test/f")


async def test_content_type_allowlist_is_case_insensitive() -> None:
    html = "<html><body>Words here.</body></html>"
    response = _FakeResponse(
        headers={"Content-Type": "TEXT/HTML; CHARSET=UTF-8"}, chunks=[html.encode()]
    )
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/": response}),
    )

    page = await reader.read("http://public.test/")

    assert page.text == "Words here."


async def test_content_type_without_charset_defaults_to_utf8() -> None:
    html = "<html><body>Hello world</body></html>"
    response = _FakeResponse(
        headers={"Content-Type": "text/html"}, chunks=[html.encode("utf-8")]
    )
    reader = _reader(
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
        opener=_opener({"http://public.test/": response}),
    )

    page = await reader.read("http://public.test/")

    assert page.text == "Hello world"


async def test_transport_error_is_not_swallowed_into_a_fabricated_page() -> None:
    # A connect timeout (or any transport error) must PROPAGATE — the reader never
    # invents a page. The caller (.2) turns it into an honest notice.
    class _RaisingCtx:
        async def __aenter__(self) -> _FakeResponse:
            raise TimeoutError("connect timed out")

        async def __aexit__(self, *exc: object) -> None:
            return None

    def opener(_url: str) -> _ResponseCtx:
        return _RaisingCtx()

    reader = _reader(resolve=_resolver({"public.test": [_PUBLIC_IP]}), opener=opener)
    with pytest.raises(TimeoutError):
        await reader.read("http://public.test/")


# --- .3 hardening: production seams (DNS getaddrinfo + real aiohttp adapter) ------------


async def test_default_resolve_extracts_ip_strings_from_getaddrinfo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeLoop:
        async def getaddrinfo(
            self, host: str, port: int, *, type: int  # noqa: A002
        ) -> list[tuple[object, ...]]:
            del host, port, type
            return [
                (socket.AF_INET, None, None, "", ("93.184.216.34", 80)),
                (socket.AF_INET6, None, None, "", ("2606:2800:220:1::1", 80, 0, 0)),
            ]

    monkeypatch.setattr(asyncio, "get_running_loop", _FakeLoop)

    addresses = await _default_resolve("example.com", 80)

    assert addresses == ["93.184.216.34", "2606:2800:220:1::1"]


async def test_production_path_disables_redirects_and_sends_fixed_ua(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Drive the real ``opener=None`` path through a fake aiohttp session: it must open
    # ONE keyless GET with redirects OFF and the fixed User-Agent, and no auth header.
    captured: dict[str, object] = {}

    class _FakeContent:
        def __init__(self, chunks: list[bytes]) -> None:
            self._chunks = chunks

        async def iter_chunked(self, _size: int) -> AsyncIterator[bytes]:
            for chunk in self._chunks:
                yield chunk

    class _FakeResp:
        def __init__(self) -> None:
            self.status = 200
            self.headers = {"Content-Type": "text/html; charset=utf-8"}
            self.content = _FakeContent(
                [b"<html><head><title>T</title></head><body>Hi there.</body></html>"]
            )

    class _FakeReqCtx:
        def __init__(self, resp: _FakeResp) -> None:
            self._resp = resp

        async def __aenter__(self) -> _FakeResp:
            return self._resp

        async def __aexit__(self, *exc: object) -> None:
            return None

    class _FakeSession:
        def __init__(self, *, timeout: object, headers: dict[str, str]) -> None:
            del timeout
            captured["headers"] = headers
            self.gets: list[tuple[str, bool]] = []
            captured["session"] = self

        def get(self, url: str, *, allow_redirects: bool) -> _FakeReqCtx:
            self.gets.append((url, allow_redirects))
            return _FakeReqCtx(_FakeResp())

        async def __aenter__(self) -> _FakeSession:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(aiohttp, "ClientSession", _FakeSession)
    reader = HttpUrlReader(
        timeout_seconds=15.0,
        max_bytes=1_000,
        max_redirects=5,
        max_chars=1_000,
        user_agent="test-ua",
        resolve=_resolver({"public.test": [_PUBLIC_IP]}),
    )

    page = await reader.read("http://public.test/a")

    assert page.title == "T"
    assert page.text == "Hi there."
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["User-Agent"] == "test-ua"
    assert "Authorization" not in headers
    session = captured["session"]
    assert isinstance(session, _FakeSession)
    assert session.gets == [("http://public.test/a", False)]
