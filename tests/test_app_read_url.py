# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Composition-root gating of the ``read_url`` skill (BOB-054 .2).

``_build_registry`` registers ``read_url`` ONLY when ``read_url.enabled`` — the
guardrail that keeps the SSRF-guarded page reader behind an explicit flag,
mirroring the ``web_search`` gate. These tests drive that gate directly over a
duck-typed recall fake (the memory-capability factories only hold the reference;
the gate never invokes recall), with introspection + diagrams + search off so the
registry holds EXACTLY the memory capabilities ± read_url. The reader is
constructed but opens no network at construction, so this stays deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.app import _build_registry

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class _FakeRecall:
    """A duck-typed MemoryRecall: never called by the registration gate."""

    async def recall(
        self, query: str, *, k: int = 5  # noqa: ARG002
    ) -> Sequence[object]:
        return []


def _config(*, read_url: Mapping[str, object] | None = None) -> dict[str, object]:
    # Introspection + diagrams + search off so the registry holds only memory caps ±
    # read_url — isolates the read_url gate from the unrelated skills.
    cfg: dict[str, object] = {
        "introspection": {"enabled": False},
        "diagrams": {"enabled": False},
        "search": {"enabled": False},
    }
    if read_url is not None:
        cfg["read_url"] = read_url
    return cfg


def _names(config: Mapping[str, object]) -> list[str]:
    registry, _sink, _renderer = _build_registry(config, recall=_FakeRecall())  # type: ignore[arg-type]
    return [
        str(tool["function"]["name"])  # type: ignore[index]
        for tool in registry.manifest()
    ]


def test_read_url_registered_when_read_url_enabled() -> None:
    names = _names(_config(read_url={"enabled": True}))

    assert "read_url" in names


def test_read_url_absent_when_read_url_disabled() -> None:
    names = _names(_config(read_url={"enabled": False}))

    assert "read_url" not in names


def test_read_url_absent_by_default_no_read_url_section() -> None:
    # No ``read_url`` section at all → the flag defaults False → skill not registered.
    names = _names(_config())

    assert "read_url" not in names
