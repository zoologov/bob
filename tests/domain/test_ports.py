# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for domain port protocols (contracts, no implementations)."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, get_type_hints, runtime_checkable

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

from bob.domain import ports


@pytest.mark.parametrize(
    "name",
    [
        "Clock",
        "EventBus",
        "LLMProvider",
        "MemoryRepo",
        "MemoryRecall",
        "Capability",
        "ToolCallingProvider",
        "Embedder",
    ],
)
def test_port_is_exported_protocol(name: str) -> None:
    # Arrange / Act
    port = getattr(ports, name)

    # Assert: every port is a typing.Protocol class.
    assert getattr(port, "_is_protocol", False) is True


def test_clock_is_runtime_checkable_and_structural() -> None:
    # Arrange
    class SystemClock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    # Act / Assert: Clock is structurally satisfiable (runtime_checkable).
    assert ports.Clock is runtime_checkable(ports.Clock)
    assert isinstance(SystemClock(), ports.Clock)


def test_clock_now_returns_datetime_annotation() -> None:
    # Assert the Clock.now contract returns a datetime.
    hints = get_type_hints(ports.Clock.now)
    assert hints["return"] is datetime


def test_event_bus_declares_publish_and_subscribe() -> None:
    # Assert EventBus port exposes publish + subscribe.
    members = dict(inspect.getmembers(ports.EventBus))
    assert "publish" in members
    assert "subscribe" in members


def test_llm_provider_declares_complete() -> None:
    assert hasattr(ports.LLMProvider, "complete")


def test_memory_repo_declares_persistence_methods() -> None:
    assert hasattr(ports.MemoryRepo, "save_episode")
    assert hasattr(ports.MemoryRepo, "load_episodes")


def test_memory_recall_declares_recall() -> None:
    assert hasattr(ports.MemoryRecall, "recall")


def test_embedder_is_exported_protocol_declaring_embed() -> None:
    # Assert the Embedder port is an exported Protocol with an ``embed`` method.
    assert "Embedder" in ports.__all__
    assert getattr(ports.Embedder, "_is_protocol", False) is True
    assert hasattr(ports.Embedder, "embed")


def test_embedder_is_structurally_satisfiable() -> None:
    # Arrange: a minimal object that satisfies the Embedder shape.
    class ConstEmbedder:
        async def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

    # Act / Assert: recognised as an Embedder (runtime_checkable, structural).
    assert isinstance(ConstEmbedder(), ports.Embedder)


def test_capability_declares_seam_attributes() -> None:
    # Assert the Capability contract exposes the stable seam (name/description/
    # input_schema/permission + async execute) used by the registry/tool-loop.
    for attr in ("name", "description", "input_schema", "permission", "execute"):
        assert hasattr(ports.Capability, attr)


def test_capability_is_structurally_satisfiable() -> None:
    # Arrange: a minimal object that satisfies the Capability shape.
    class Echo:
        name = "echo"
        description = "Echo the args back."
        input_schema: ClassVar[dict[str, object]] = {"type": "object", "properties": {}}
        permission = "safe"

        async def execute(self, args: dict[str, object]) -> object:
            return args

    # Act / Assert: it is recognised as a Capability (runtime_checkable).
    assert isinstance(Echo(), ports.Capability)


def test_tool_call_and_result_value_objects_exist() -> None:
    # Assert the tool-calling value objects carry the expected fields.
    call = ports.ToolCall(id="c1", name="recall_memory", arguments={"query": "x"})
    assert call.id == "c1"
    assert call.name == "recall_memory"
    assert call.arguments == {"query": "x"}
    result = ports.ToolCallResult(text="", tool_calls=(call,))
    assert result.text == ""
    assert result.tool_calls == (call,)


def test_tool_calling_provider_declares_complete_with_tools() -> None:
    assert hasattr(ports.ToolCallingProvider, "complete_with_tools")


def test_web_search_value_objects_are_frozen() -> None:
    # Assert the web-search value objects carry the expected fields and are immutable.
    source = ports.WebSource(title="Title", url="https://example.com")
    assert source.title == "Title"
    assert source.url == "https://example.com"
    result = ports.WebSearchResult(answer="grounded answer", sources=(source,))
    assert result.answer == "grounded answer"
    assert result.sources == (source,)
    with pytest.raises(AttributeError):
        source.url = "https://other.com"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.answer = "tampered"  # type: ignore[misc]


def test_web_search_value_objects_use_slots_and_reject_new_attributes() -> None:
    # slots=True: the value objects carry no __dict__ and reject ad-hoc attributes,
    # so a recalled source/result cannot be silently extended downstream.
    source = ports.WebSource(title="T", url="https://example.com")
    result = ports.WebSearchResult(answer="a")
    assert not hasattr(source, "__dict__")
    assert not hasattr(result, "__dict__")
    with pytest.raises(AttributeError):
        source.extra = "x"  # type: ignore[attr-defined]
    with pytest.raises(AttributeError):
        result.extra = "x"  # type: ignore[attr-defined]


def test_web_search_result_defaults_to_empty_sources() -> None:
    # ``sources`` defaults to the empty tuple — a grounded answer with nothing worth
    # citing is valid (not an error), so callers can omit sources entirely.
    result = ports.WebSearchResult(answer="grounded")
    assert result.sources == ()


def test_web_search_provider_is_exported_runtime_checkable_protocol() -> None:
    # Assert the WebSearchProvider port is an exported, structural Protocol.
    assert "WebSearchProvider" in ports.__all__
    assert getattr(ports.WebSearchProvider, "_is_protocol", False) is True
    assert hasattr(ports.WebSearchProvider, "search")


def test_web_page_value_object_is_frozen_and_slotted() -> None:
    # Assert the read_url value object carries final-url/title/text and is immutable.
    page = ports.WebPage(url="https://example.com/a", title="Title", text="body")
    assert page.url == "https://example.com/a"
    assert page.title == "Title"
    assert page.text == "body"
    assert not hasattr(page, "__dict__")
    with pytest.raises(AttributeError):
        page.text = "tampered"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        page.extra = "x"  # type: ignore[attr-defined]


def test_url_reader_is_exported_runtime_checkable_protocol() -> None:
    # Assert the UrlReader port is an exported, structural Protocol declaring read().
    assert "UrlReader" in ports.__all__
    assert getattr(ports.UrlReader, "_is_protocol", False) is True
    assert hasattr(ports.UrlReader, "read")


def test_web_search_provider_is_structurally_satisfiable() -> None:
    # Arrange: a minimal object that satisfies the WebSearchProvider shape.
    class ConstSearch:
        async def search(self, query: str) -> ports.WebSearchResult:
            return ports.WebSearchResult(answer=query, sources=())

    # Act / Assert: recognised as a WebSearchProvider (runtime_checkable, structural).
    assert isinstance(ConstSearch(), ports.WebSearchProvider)


def _imported_modules(module_source: str) -> set[str]:
    tree = ast.parse(module_source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_domain_imports_nothing_outward() -> None:
    # Architecture guard: the domain layer must not import application/infrastructure.
    source = Path(inspect.getfile(ports)).read_text(encoding="utf-8")
    imported = _imported_modules(source)
    outward = [
        name for name in imported if name.startswith(("bob.application", "bob.infrastructure"))
    ]
    assert outward == []
