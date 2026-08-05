# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the architecture-drawing scenarios (BOB-091.1).

Binds ``architecture_drawing.feature`` to
:mod:`tests.acceptance.architecture_drawing_harness`, which drives the REAL tool-loop
over the REAL architecture tools + a scripted fake port, and the REAL composition-root
registration gate for the flag scenarios. Every Then asserts an OBSERVABLE boundary
value — the tool result fed to the model, the argv-shaping call the port received, or the
advertised manifest — never internals.

pytest-bdd scenarios are synchronous, so the async harness runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from bob.capabilities.adapters.diagrams.mmdc_renderer import DiagramRenderError
from tests.acceptance.architecture_drawing_harness import (
    draw_with_the_picture_seam,
    offered_tool_names,
    run_architecture_tool,
)
from tests.application.capabilities.fakes import (
    FakeDiagramRenderer,
    FakeRepoIntrospector,
)

if TYPE_CHECKING:
    from bob.capabilities.ports import DiagramResult

scenarios("../features/architecture_drawing.feature")

_ARCHITECTURE_TOOLS = ("draw_architecture", "architecture_impact")


@dataclass(slots=True)
class _Ctx:
    """The slate the steps share: the scripted port + the observed boundary values."""

    introspector: FakeRepoIntrospector = field(default_factory=FakeRepoIntrospector)
    result: str = ""
    description: str = ""
    offered_tools: list[str] = field(default_factory=list)
    # BOB-091.6: the render seam + what actually landed in the turn's send queue.
    renderer: FakeDiagramRenderer | None = None
    queued_pictures: tuple[DiagramResult, ...] = ()


@pytest.fixture
def ctx() -> _Ctx:
    return _Ctx()


# --- Given --------------------------------------------------------------------


@given(parsers.parse('граф архитектуры отдаёт схему "{mermaid}"'))
def graph_returns_diagram(ctx: _Ctx, mermaid: str) -> None:
    ctx.introspector = FakeRepoIntrospector(diagram=mermaid.replace("\\n", "\n"))


@given("граф архитектуры вернул форму узла вместо запрошенных внутренностей")
def graph_fell_back_to_the_node_form(ctx: _Ctx) -> None:
    ctx.introspector = FakeRepoIntrospector(
        diagram='graph LR\n    memory["memory"]\n    memory --> bob',
        diagram_form="node",
    )


@given(parsers.parse('граф влияния отдаёт сжатый ответ про "{ref}"'))
def impact_returns_digest(ctx: _Ctx, ref: str) -> None:
    ctx.introspector = FakeRepoIntrospector(
        impact_text=(
            f"{ref} (feature) — Memory module.\n"
            "Зависит от: bob-domain (domain), persistence (component).\n"
            "Влияет на: capabilities (feature)."
        )
    )


@given("граф влияния пуст")
def impact_is_empty(ctx: _Ctx) -> None:
    ctx.introspector = FakeRepoIntrospector(impact_text="")


@given("локальный рендерер работает")
def the_local_renderer_works(ctx: _Ctx) -> None:
    ctx.renderer = FakeDiagramRenderer()


@given("локальный рендерер недоступен")
def the_local_renderer_is_unavailable(ctx: _Ctx) -> None:
    # The shape of a machine without mermaid-cli (or a timeout / broken source).
    ctx.renderer = FakeDiagramRenderer(
        raises=DiagramRenderError("mmdc is not installed")
    )


@given("ход в разговоре")
def a_turn(ctx: _Ctx) -> None:
    assert ctx.result == ""


# --- When ---------------------------------------------------------------------


@when("Боб просит нарисовать архитектуру целиком")
def bob_asks_for_the_overview(ctx: _Ctx) -> None:
    if ctx.renderer is not None:
        ctx.result, ctx.queued_pictures = asyncio.run(
            draw_with_the_picture_seam(ctx.introspector, renderer=ctx.renderer)
        )
        return
    ctx.result, ctx.description = asyncio.run(
        run_architecture_tool(
            ctx.introspector, tool="draw_architecture", arguments={}
        )
    )


@when(parsers.parse('Боб просит подробную схему узла "{ref}" на глубину {depth:d}'))
def bob_asks_for_a_node(ctx: _Ctx, ref: str, depth: int) -> None:
    ctx.result, ctx.description = asyncio.run(
        run_architecture_tool(
            ctx.introspector,
            tool="draw_architecture",
            arguments={"ref": ref, "depth": depth},
        )
    )


@when(parsers.parse('Боб просит показать внутренности узла "{ref}"'))
def bob_asks_for_internals(ctx: _Ctx, ref: str) -> None:
    ctx.result, ctx.description = asyncio.run(
        run_architecture_tool(
            ctx.introspector,
            tool="draw_architecture",
            arguments={"internals_of": ref},
        )
    )


@when(parsers.parse('Боб спрашивает, что сломается, если тронуть "{ref}"'))
def bob_asks_about_impact(ctx: _Ctx, ref: str) -> None:
    ctx.result, ctx.description = asyncio.run(
        run_architecture_tool(
            ctx.introspector, tool="architecture_impact", arguments={"ref": ref}
        )
    )


@when("инструменты собираются с выключенным флагом архитектуры")
def tools_built_with_flag_off(ctx: _Ctx) -> None:
    ctx.offered_tools = offered_tool_names(architecture_tools=False)


@when("инструменты собираются с включённым флагом архитектуры")
def tools_built_with_flag_on(ctx: _Ctx) -> None:
    ctx.offered_tools = offered_tool_names(architecture_tools=True)


# --- Then ---------------------------------------------------------------------


@then(parsers.parse('результат инструмента, ушедший модели, несёт "{fragment}"'))
def tool_result_carries(ctx: _Ctx, fragment: str) -> None:
    assert fragment in ctx.result, (
        f"реальный факт {fragment!r} не дошёл до модели: {ctx.result!r}"
    )


@then("картинка встала в очередь отправки этого хода")
def a_picture_is_queued_for_this_turn(ctx: _Ctx) -> None:
    # 🔴 Наблюдаемый факт вместо обещания: в per-turn синке, который путь ответа сливает
    # в чат фотографией, лежит настоящий отрендеренный PNG.
    assert len(ctx.queued_pictures) == 1, (
        f"owner не получит картинку: в очереди {len(ctx.queued_pictures)}"
    )
    assert ctx.queued_pictures[0].png
    assert ctx.queued_pictures[0].caption


@then("в очереди отправки картинки нет")
def no_picture_is_queued(ctx: _Ctx) -> None:
    assert ctx.queued_pictures == ()


@then("результат инструмента, ушедший модели, честно предупреждает, что картинки не будет")
def result_admits_the_picture_is_missing(ctx: _Ctx) -> None:
    lowered = ctx.result.lower()
    assert "не удалось" in lowered, (
        f"Боб должен сказать, что картинки не будет: {ctx.result!r}"
    )
    assert "уже отрисована" not in lowered, "нельзя делать вид, что картинка ушла"


@then(parsers.parse('в граф ушёл запрос узла "{ref}" с глубиной {depth:d}'))
def graph_got_node_request(ctx: _Ctx, ref: str, depth: int) -> None:
    assert ctx.introspector.diagram_calls == [(ref, depth, None)]


@then("результат инструмента, ушедший модели, честно предупреждает про внутренности")
def result_warns_about_internals(ctx: _Ctx) -> None:
    lowered = ctx.result.lower()
    assert "внутренност" in lowered, (
        f"Боб должен предупредить, что это не внутренности: {ctx.result!r}"
    )
    assert "graph LR" in ctx.result, "схема связей всё равно должна прийти"


@then("в результате инструмента нет терминальной графики")
def result_has_no_terminal_graphics(ctx: _Ctx) -> None:
    for glyph in ("╭", "╰", "│", "├", "└", "──"):
        assert glyph not in ctx.result


@then("результат инструмента, ушедший модели, честно сообщает «не нашёл»")
def result_is_honestly_empty(ctx: _Ctx) -> None:
    assert "не нашёл" in ctx.result.lower(), (
        f"неизвестный узел должен отвечать честно: {ctx.result!r}"
    )


@then("инструменты архитектуры не предлагаются")
def architecture_tools_absent(ctx: _Ctx) -> None:
    for tool in _ARCHITECTURE_TOOLS:
        assert tool not in ctx.offered_tools, f"{tool} предложен при выключенном флаге"


@then("инструменты архитектуры предлагаются")
def architecture_tools_present(ctx: _Ctx) -> None:
    for tool in _ARCHITECTURE_TOOLS:
        assert tool in ctx.offered_tools
