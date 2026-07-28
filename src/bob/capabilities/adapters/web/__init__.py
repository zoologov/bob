# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=infrastructure

"""Web-page reading infrastructure (BOB-054).

The ``read_url`` skill's outward edge: an :class:`bob.domain.ports.UrlReader` that
fetches a concrete URL over ``aiohttp`` behind a 🔴 SSRF guard and extracts readable
text with the stdlib ``html.parser``. Kept apart from ``infrastructure/llm`` — reading
a page is not an LLM call.
"""

from bob.capabilities.adapters.web.factory import build_url_reader
from bob.capabilities.adapters.web.http_url_reader import (
    HttpUrlReader,
    SsrfBlockedError,
    UrlReadError,
)

__all__ = [
    "HttpUrlReader",
    "SsrfBlockedError",
    "UrlReadError",
    "build_url_reader",
]
