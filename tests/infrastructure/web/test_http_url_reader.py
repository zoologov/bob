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

from typing import TYPE_CHECKING

import pytest

from bob.domain.ports import UrlReader, WebPage
from bob.infrastructure.web.http_url_reader import (
    HttpUrlReader,
    SsrfBlockedError,
    UrlReadError,
    _extract_text,
    _stream_body,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.infrastructure.web.http_url_reader import (
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


def _opener(routes: dict[str, _FakeResponse]) -> UrlOpener:
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
