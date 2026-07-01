# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``read_url`` — the concrete-URL page-reading skill (BOB-054 .2).

A thin wrapper over the :class:`~bob.domain.ports.UrlReader` port (the twin of
``web_search``, BOB-053): it exposes the stable :class:`Capability` contract,
validates the ``url``, delegates to the port and projects the fetched page
COMPACTLY (url + title + excerpt) into the tool-loop — Bob synthesises the final
reply in his own voice. It never fabricates page content: a blank url is answered
honestly WITHOUT calling the reader, a transient failure is retried a bounded
number of times and then surfaced as an HONEST "couldn't open" notice with
anti-confabulation guidance, and a 🔴 :class:`SsrfBlockedError` is refused
IMMEDIATELY (deterministic block — never retried). Deterministic on a fake port +
an injected sleep — no network, no disk, no delay.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.application.capabilities.read_url import make_read_url_capability
from bob.domain.ports import WebPage
from bob.infrastructure.web import SsrfBlockedError, UrlReadError


class _FakeUrlReader:
    """A scripted :class:`UrlReader`: records urls, returns a canned page or raises."""

    def __init__(
        self,
        *,
        page: WebPage | None = None,
        error: Exception | None = None,
    ) -> None:
        self._page = page if page is not None else WebPage(url="", title="", text="")
        self._error = error
        self.urls: list[str] = []

    async def read(self, url: str) -> WebPage:
        self.urls.append(url)
        if self._error is not None:
            raise self._error
        return self._page


class _FlakyUrlReader:
    """Fails ``fail_times`` then returns ``page``; records call count + urls."""

    def __init__(
        self,
        *,
        fail_times: int,
        page: WebPage | None = None,
        error: Exception | None = None,
    ) -> None:
        self._fail_times = fail_times
        self._page = (
            page if page is not None else WebPage(url="https://x", title="ok", text="body")
        )
        self._error = error if error is not None else RuntimeError("transient")
        self.calls = 0
        self.urls: list[str] = []

    async def read(self, url: str) -> WebPage:
        self.urls.append(url)
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error
        return self._page


class _RecordingSleep:
    """An injectable backoff sleep that records its delays and never really waits."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def test_capability_advertises_the_read_url_contract() -> None:
    cap = make_read_url_capability(_FakeUrlReader())

    assert cap.name == "read_url"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["url"] == {"type": "string"}
    assert schema["required"] == ["url"]


def test_description_distinguishes_read_url_from_web_search() -> None:
    # Kept tight so the model only reaches for it on a concrete URL to read — and
    # not confused with ``web_search`` (which searches by topic).
    cap = make_read_url_capability(_FakeUrlReader())

    desc = cap.description.lower()
    assert "url" in desc
    assert "web_search" in desc  # explicitly names the sibling it must not be confused with


async def test_execute_projects_page_compactly() -> None:
    reader = _FakeUrlReader(
        page=WebPage(
            url="https://example.com/article",
            title="Заголовок",
            text="Читаемый текст статьи, уже обрезанный читателем.",
        )
    )
    cap = make_read_url_capability(reader)

    result = await cap.execute({"url": "https://example.com/article"})

    assert reader.urls == ["https://example.com/article"]
    assert isinstance(result, Mapping)
    assert result["url"] == "https://example.com/article"
    assert result["title"] == "Заголовок"
    assert result["excerpt"] == "Читаемый текст статьи, уже обрезанный читателем."
    # A compact projection — no raw dump beyond the three fields.
    assert set(result.keys()) == {"url", "title", "excerpt"}


async def test_execute_with_blank_url_is_honest_and_skips_the_reader() -> None:
    reader = _FakeUrlReader()
    cap = make_read_url_capability(reader)

    result = await cap.execute({"url": "   "})

    assert reader.urls == []  # reader NOT called on a blank url
    assert isinstance(result, Mapping)
    assert "ссылк" in str(result["excerpt"]).lower()
    assert "guidance" not in result  # the blank reply is not a failure notice


@pytest.mark.parametrize("url", ["", "   ", "\t", "\n", " \t\n "])
async def test_execute_blank_url_variants_skip_the_reader(url: str) -> None:
    reader = _FakeUrlReader()
    cap = make_read_url_capability(reader)

    result = await cap.execute({"url": url})

    assert reader.urls == []
    assert isinstance(result, Mapping)


async def test_execute_requires_a_string_url() -> None:
    cap = make_read_url_capability(_FakeUrlReader())

    with pytest.raises(ValueError, match="url"):
        await cap.execute({"url": 123})


async def test_execute_with_missing_url_key_raises() -> None:
    cap = make_read_url_capability(_FakeUrlReader())

    with pytest.raises(ValueError, match="url"):
        await cap.execute({})


async def test_execute_with_none_url_raises() -> None:
    cap = make_read_url_capability(_FakeUrlReader())

    with pytest.raises(ValueError, match="url"):
        await cap.execute({"url": None})


async def test_execute_retries_transient_failure_then_succeeds() -> None:
    # .2: read_url is ESSENTIAL when invoked — a transient network blip is retried
    # (bounded, with backoff through the injected sleep) before giving up.
    reader = _FlakyUrlReader(
        fail_times=2,
        page=WebPage(url="https://x/y", title="T", text="содержимое"),
    )
    sleep = _RecordingSleep()
    cap = make_read_url_capability(reader, attempts=3, backoff_seconds=0.5, sleep=sleep)

    result = await cap.execute({"url": "https://x/y"})

    assert reader.calls == 3  # two failures retried, third succeeds
    assert sleep.delays == [0.5, 0.5]  # backoff awaited BETWEEN attempts only
    assert isinstance(result, Mapping)
    assert result["title"] == "T"
    assert result["excerpt"] == "содержимое"


async def test_execute_exhausts_retries_then_returns_honest_notice() -> None:
    # 🔴 Invariant: a persistent transient failure NEVER yields fabricated content.
    # After the bounded retry the skill returns an HONEST "couldn't open" notice with
    # anti-confabulation guidance — Bob tells the user the truth.
    reader = _FlakyUrlReader(fail_times=99, error=UrlReadError("network down"))
    sleep = _RecordingSleep()
    cap = make_read_url_capability(reader, attempts=3, backoff_seconds=0.5, sleep=sleep)

    result = await cap.execute({"url": "https://example.com/x"})

    assert reader.calls == 3  # bounded retry attempted, then gave up
    assert sleep.delays == [0.5, 0.5]
    assert isinstance(result, Mapping)
    excerpt = str(result["excerpt"]).lower()
    assert "не смог" in excerpt or "не удалось" in excerpt
    assert "guidance" in result
    assert str(result["guidance"]).strip()


async def test_ssrf_blocked_is_refused_immediately_without_retry() -> None:
    # 🔴 Invariant: an SsrfBlockedError is DETERMINISTIC — retrying a blocked-internal
    # URL is pointless, so the reader is called exactly once and the backoff sleep is
    # NEVER invoked. The skill still returns the honest "couldn't open" notice.
    reader = _FakeUrlReader(error=SsrfBlockedError("blocked private address"))
    sleep = _RecordingSleep()
    cap = make_read_url_capability(reader, attempts=3, backoff_seconds=0.5, sleep=sleep)

    result = await cap.execute({"url": "http://169.254.169.254/latest/meta-data"})

    assert reader.urls == ["http://169.254.169.254/latest/meta-data"]
    assert len(reader.urls) == 1  # NO retry for a deterministic block
    assert sleep.delays == []  # backoff never awaited
    assert isinstance(result, Mapping)
    assert "guidance" in result  # honest notice, never fabricated content


async def test_failure_notice_never_leaks_fabricated_content() -> None:
    # 🔴 No confabulation: on failure the projection carries no page body — only the
    # honest caveat + anti-confabulation guidance.
    reader = _FakeUrlReader(error=UrlReadError("login wall"))
    cap = make_read_url_capability(reader, attempts=1)

    result = await cap.execute({"url": "https://paywall.example/secret"})

    assert isinstance(result, Mapping)
    assert result["url"] == "https://paywall.example/secret"
    assert str(result["guidance"]).strip()


async def test_single_attempt_transient_failure_calls_once_without_backoff() -> None:
    # With attempts=1 the bounded retry degenerates to a single call: the reader is
    # invoked exactly once, the injected backoff is NEVER awaited, and a persistent
    # failure still surfaces the honest notice — never fabricated content.
    reader = _FlakyUrlReader(fail_times=99, error=UrlReadError("down"))
    sleep = _RecordingSleep()
    cap = make_read_url_capability(reader, attempts=1, backoff_seconds=0.5, sleep=sleep)

    result = await cap.execute({"url": "https://x/y"})

    assert reader.calls == 1  # attempts=1 → one call, no retry
    assert sleep.delays == []  # no backoff with a single attempt
    assert isinstance(result, Mapping)
    assert "guidance" in result


def test_make_capability_rejects_non_positive_attempts() -> None:
    with pytest.raises(ValueError, match="attempts"):
        make_read_url_capability(_FakeUrlReader(), attempts=0)


def test_make_capability_rejects_negative_backoff() -> None:
    with pytest.raises(ValueError, match="backoff"):
        make_read_url_capability(_FakeUrlReader(), backoff_seconds=-1.0)
