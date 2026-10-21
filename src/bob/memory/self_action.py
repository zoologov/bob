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

Инварианты ядра: контент всегда открывается «я …» (INV-1 первое лицо); сбой и
runaway помечаются ``is_anomaly`` и тегом ``anomaly`` — Боб честно признаёт промах,
а не приписывает его внешним силам (INV-4 разделение акторства).

🔴 Боб присваивает себе РОВНО то, что сделал (BOB-089, bob-a6b.8). У успешного финала
coding-сессии два разных поступка, и путать их нельзя: на gh-пути Боб открыл PR
(:attr:`SelfActionKind.CODING_FINISHED`), на форк-пути он довёл работу до ветки в своём
форке и отдал ссылку, а «Create pull request» жмёт owner
(:attr:`SelfActionKind.CODING_HANDED_OFF`). Эпизод автобиографии — источник будущих
ответов Боба о себе, поэтому заявление о несовершённом действии здесь становится
конфабуляцией с провенансом «я это помню, я сам так сделал» — ровно тем классом, против
которого BOB-090.C строил анти-конфабуляционный провенанс. Выбор поступка по факту делает
:func:`coding_terminal_kind`.

Простой провайдера (BOB-116, bob-i83.3): :attr:`SelfActionKind.OUTAGE_RECOVERED` — эпизод
«я молчал с … по …: <причина по-человечески>, думать было нечем. Теперь снова могу.»
Факты простоя несёт типизированный :class:`OutageSpan`, а не строка ``detail``: ``detail``
остальных видов выводится в текст как есть, а здесь нужны даты, класс отказа и провайдер,
которые рендер раскладывает сам. Время выводится так, как его несёт ``datetime`` — пояс
выбирает вызывающий адаптер (сборка переводит в пояс процесса), ядро часов не читает, — и
подписывается смещением («по 06:42 +03:00»): тот же пояс и та же подпись, что в сообщении
владельцу и в GUPPI ``/status`` (:mod:`bob.kernel.local_time`, bob-i83.15). Период,
длительность, говорящий и причина — те же слова, что у владельца и в ``/status``, из одного
дома :mod:`bob.kernel.ru_text` (ревью M3, bob-i83.20): «со 2 октября» здесь и там одинаково.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from bob.kernel.ru_text import duration, failure_then, period, provider_speaker

if TYPE_CHECKING:
    from datetime import datetime

__all__ = [
    "OutageSpan",
    "RenderedSelfAction",
    "SelfAction",
    "SelfActionKind",
    "coding_terminal_kind",
    "describe_self_action",
]

# Tag vocabulary — free-form recall labels shared with the episodic log.
_TAG_SELF = "self"
_TAG_CODING = "coding"
_TAG_TOOLS = "tools"
_TAG_ANOMALY = "anomaly"
_TAG_OUTAGE = "outage"


class SelfActionKind(StrEnum):
    """Класс самодействия Боба (значение = голая строка в ``episodic_log``).

    Прецедент строкового enum — :class:`bob.coding.state.CodingSessionState`. Coding
    покрывает жизненный цикл сессии (старт, два разных успешных финала, прерывание,
    провал, runaway-флуд); tool — коалесцированный итог tool-loop за ход и падение
    инструмента; outage — возвращение Боба после простоя провайдера (BOB-116).
    """

    CODING_STARTED = "coding_started"
    CODING_FINISHED = "coding_finished"
    # 🔴 Второй успешный финал (BOB-089): работа доехала до ветки в форке Боба, ссылка
    # отдана owner'у, PR Боб НЕ открывал. Отдельный вид, а не оттенок формулировки:
    # это другой поступок, и присваивать себе чужое нажатие Боб не должен.
    CODING_HANDED_OFF = "coding_handed_off"
    CODING_ABORTED = "coding_aborted"
    CODING_FAILED = "coding_failed"
    CODING_RUNAWAY = "coding_runaway"
    TOOL_USE = "tool_use"
    TOOL_FAILURE = "tool_failure"
    # BOB-116: провайдер снова отвечает после DEGRADED — Боб помнит, что молчал и почему.
    # Не аномалия: молчание — не промах Боба, причину он называет честно (INV-4).
    OUTAGE_RECOVERED = "outage_recovered"


@dataclass(frozen=True, slots=True)
class OutageSpan:
    """Факты простоя провайдера для эпизода :attr:`SelfActionKind.OUTAGE_RECOVERED`.

    ``since``/``until`` — начало отказов и первый успех (оба в поясе, в котором Боб
    рассказывает о времени; выбирает вызывающий). ``failure_class`` — класс отказа
    вызывающего слоя (``auth``/``rate``/``server``/``timeout``/``connection``/``shape``,
    незнакомый класс называется как есть, ``None`` — общая формулировка). ``provider`` — id
    провайдера монитора (:data:`bob.kernel.provider_health.TIER0_PRIMARY` и соседи).
    """

    since: datetime
    until: datetime
    failure_class: str | None
    provider: str

    def __post_init__(self) -> None:
        if self.until < self.since:
            msg = f"OutageSpan: until {self.until} is before since {self.since}"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SelfAction:
    """Структурированная запись поступка Боба (вход рендера).

    ``target`` — задача/файлы/инструменты (коротко), ``detail`` — причина сбоя и т.п.
    Оба опциональны: рендер деградирует к формулировке без «…»-кавычек. ``outage`` —
    факты простоя, читает только :attr:`SelfActionKind.OUTAGE_RECOVERED`.
    """

    kind: SelfActionKind
    target: str | None = None
    detail: str | None = None
    outage: OutageSpan | None = None


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
        SelfActionKind.CODING_HANDED_OFF,
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


def _area_tag(kind: SelfActionKind) -> str:
    """Область поступка: coding, outage или tools."""
    if kind in _CODING_KINDS:
        return _TAG_CODING
    if kind is SelfActionKind.OUTAGE_RECOVERED:
        return _TAG_OUTAGE
    return _TAG_TOOLS


def _tags_for(kind: SelfActionKind) -> tuple[str, ...]:
    """``self`` + область (coding/outage/tools) + ``anomaly`` для сбоя/runaway."""
    area = _area_tag(kind)
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
        case SelfActionKind.CODING_HANDED_OFF:
            head = f"я довёл «{target}»" if target else "я довёл работу"
            content = f"{head} до ветки в своём форке и отдал ссылку — PR не открывал"
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
        case SelfActionKind.OUTAGE_RECOVERED:
            content = _outage_story(action.outage)
    return content


# --- Простой провайдера от первого лица (BOB-116) ------------------------------------

_OUTAGE_TAIL = "думать было нечем. Теперь снова могу."


def _outage_story(span: OutageSpan | None) -> str:
    """«я молчал …: причина, думать было нечем. Теперь снова могу.»; без фактов — коротко."""
    if span is None:
        return f"я молчал — {_OUTAGE_TAIL}"
    when = period(span.since, span.until)
    lasted = duration((span.until - span.since).total_seconds())
    cause = failure_then(span.failure_class, provider_speaker(span.provider))
    return f"я молчал {when} ({lasted}): {cause}, {_OUTAGE_TAIL}"


def coding_terminal_kind(*, opened_pr: bool) -> SelfActionKind:
    """Какой поступок Боб записывает на успешном финале сессии — по ФАКТУ, а не по надежде.

    ``opened_pr`` — тот же самый признак пути, которым композиция уже развела адаптер
    интеграции и терминальную реплику одним решением
    (``_build_pr_integration`` → ``CodingAssistant(opens_pr=…)``, BOB-089.D). Отдельного
    флага здесь нет сознательно: два источника «открыт ли PR» рано или поздно разойдутся, и
    расхождение проявится именно как ложное воспоминание Боба о себе.

    ``True`` → :attr:`SelfActionKind.CODING_FINISHED` («открыл PR» — так и было, gh-путь);
    ``False`` → :attr:`SelfActionKind.CODING_HANDED_OFF` (работа доведена до ветки в форке,
    ссылка отдана, нажимает owner).
    """
    return SelfActionKind.CODING_FINISHED if opened_pr else SelfActionKind.CODING_HANDED_OFF


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
