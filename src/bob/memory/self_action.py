# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=domain

"""Самодействие Боба от первого лица — чистое доменное ядро (BOB-079.1).

Превращает структурированную запись поступка Боба (:class:`SelfAction`) в русскую
формулировку ОТ ПЕРВОГО ЛИЦА (:class:`RenderedSelfAction`) — теги + флаг аномалии.
I/O-free и детерминированное (mutation-цель): БД, время и sender живут в адаптере.

Инвариант ядра: контент всегда открывается «я …» (INV-1 первое лицо); сбой и
runaway помечаются ``is_anomaly`` и тегом ``anomaly`` — Боб честно признаёт промах,
а не приписывает его внешним силам (INV-4 разделение акторства).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "RenderedSelfAction",
    "SelfAction",
    "SelfActionKind",
    "describe_self_action",
]

# Tag vocabulary — free-form recall labels shared with the episodic log.
_TAG_SELF = "self"
_TAG_CODING = "coding"
_TAG_TOOLS = "tools"
_TAG_ANOMALY = "anomaly"


class SelfActionKind(StrEnum):
    """Класс самодействия Боба (значение = голая строка в ``episodic_log``).

    Прецедент строкового enum — :class:`bob.coding.state.CodingSessionState`. Coding
    покрывает жизненный цикл сессии (старт/финиш/прерывание/провал/runaway-флуд);
    tool — коалесцированный итог tool-loop за ход и падение инструмента.
    """

    CODING_STARTED = "coding_started"
    CODING_FINISHED = "coding_finished"
    CODING_ABORTED = "coding_aborted"
    CODING_FAILED = "coding_failed"
    CODING_RUNAWAY = "coding_runaway"
    TOOL_USE = "tool_use"
    TOOL_FAILURE = "tool_failure"


@dataclass(frozen=True, slots=True)
class SelfAction:
    """Структурированная запись поступка Боба (вход рендера).

    ``target`` — задача/файлы/инструменты (коротко), ``detail`` — причина сбоя и т.п.
    Оба опциональны: рендер деградирует к формулировке без «…»-кавычек.
    """

    kind: SelfActionKind
    target: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class RenderedSelfAction:
    """Результат рендера: контент ОТ ПЕРВОГО ЛИЦА, теги и флаг аномалии."""

    content: str
    tags: tuple[str, ...]
    is_anomaly: bool


# Классификация вида для тегов/аномалии — производная, а не разбросанные литералы.
_CODING_KINDS = frozenset(
    {
        SelfActionKind.CODING_STARTED,
        SelfActionKind.CODING_FINISHED,
        SelfActionKind.CODING_ABORTED,
        SelfActionKind.CODING_FAILED,
        SelfActionKind.CODING_RUNAWAY,
    }
)
_ANOMALY_KINDS = frozenset(
    {
        SelfActionKind.CODING_FAILED,
        SelfActionKind.CODING_RUNAWAY,
        SelfActionKind.TOOL_FAILURE,
    }
)


def _detail_suffix(detail: str | None) -> str:
    """``": {detail}"`` when a reason is given, else empty."""
    return f": {detail}" if detail else ""


def _tags_for(kind: SelfActionKind) -> tuple[str, ...]:
    """``self`` + область (coding/tools) + ``anomaly`` для сбоя/runaway."""
    area = _TAG_CODING if kind in _CODING_KINDS else _TAG_TOOLS
    tags = [_TAG_SELF, area]
    if kind in _ANOMALY_KINDS:
        tags.append(_TAG_ANOMALY)
    return tuple(tags)


def _content_for(action: SelfAction) -> str:
    """Русская фраза от первого лица; без ``target`` — мягкая формулировка без «…»."""
    target, detail = action.target, action.detail
    match action.kind:
        case SelfActionKind.CODING_STARTED:
            content = (
                f"я взялся за «{target}» в кодере" if target else "я взялся за работу в кодере"
            )
        case SelfActionKind.CODING_FINISHED:
            content = (
                f"я доделал «{target}», открыл PR" if target else "я доделал работу, открыл PR"
            )
        case SelfActionKind.CODING_ABORTED:
            content = (
                f"я прервал сессию по «{target}» — меня остановили"
                if target
                else "я прервал сессию — меня остановили"
            )
        case SelfActionKind.CODING_FAILED:
            head = f"я не справился с «{target}»" if target else "я не справился"
            content = f"{head} — сессия упала{_detail_suffix(detail)}"
        case SelfActionKind.CODING_RUNAWAY:
            head = f"я залип на «{target}»" if target else "я залип"
            content = f"{head} — флудил правками, пришлось себя осадить"
        case SelfActionKind.TOOL_USE:
            content = (
                f"я воспользовался инструментами: {target}"
                if target
                else "я воспользовался инструментами"
            )
        case SelfActionKind.TOOL_FAILURE:
            head = (
                f"я попробовал {target}"
                if target
                else "я попробовал воспользоваться инструментом"
            )
            content = f"{head} — не вышло{_detail_suffix(detail)}"
    return content


def describe_self_action(action: SelfAction) -> RenderedSelfAction:
    """Отрендерить самодействие в русскую фразу от первого лица + теги + флаг.

    Детерминированный рендер по :class:`SelfActionKind`. Контент всегда открывается
    «я …» (INV-1); сбой/runaway помечаются ``is_anomaly`` и тегом ``anomaly``.
    """
    return RenderedSelfAction(
        content=_content_for(action),
        tags=_tags_for(action.kind),
        is_anomaly=action.kind in _ANOMALY_KINDS,
    )
