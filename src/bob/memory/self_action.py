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
выбирает вызывающий адаптер, ядро часов не читает.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime, timedelta

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
    неизвестный или ``None`` — общая формулировка). ``provider`` — id провайдера монитора
    (``tier0-primary``/``tier0-understudy``/``tier1``).
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

_SECONDS_PER_MINUTE = 60
_MINUTES_PER_HOUR = 60
_HOURS_PER_DAY = 24
_UNIT_FORMS = (
    ("день", "дня", "дней"),
    ("час", "часа", "часов"),
    ("минута", "минуты", "минут"),
)
_TEENS = range(11, 15)
_FEW = range(2, 5)
_LAST_DIGIT_ONE = 1
_DECIMAL = 10
_CENTURY = 100
# «со 2 октября», но «с 1/3/22 октября»: «со» — только перед «второго».
_DAY_TAKING_SO = 2

_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

# Дублёр живёт на машине Боба; все прочие провайдеры монитора — облако. id совпадает с
# provider_id монитора (RFC BOB-116, ``application/router/health_monitor.py``).
_LOCAL_UNDERSTUDY = "tier0-understudy"


@dataclass(frozen=True, slots=True)
class _Speaker:
    """Кто не давал Бобу думать — в тех формах, которых требуют фразы причин."""

    nominative: str
    genitive: str
    past_ending: str  # окончание глагола прошедшего времени: «облако не отвечало»


_CLOUD = _Speaker(nominative="облако", genitive="облака", past_ending="о")
_UNDERSTUDY = _Speaker(nominative="дублёр", genitive="дублёра", past_ending="")

# Причина по-человечески, без кода HTTP: шаблон с подстановкой говорящего.
_CAUSE_BY_CLASS = {
    "auth": "{n} не пускал{e} меня по ключу",
    "rate": "{n} просил{e} подождать",
    "server": "{n} падал{e} у себя",
    "timeout": "{n} не отвечал{e}",
    "connection": "до {g} было не достучаться",
    "shape": "{n} отвечал{e} бессвязно",
}
_CAUSE_UNKNOWN = "{n} не работал{e}"

_OUTAGE_TAIL = "думать было нечем. Теперь снова могу."


def _outage_story(span: OutageSpan | None) -> str:
    """«я молчал …: причина, думать было нечем. Теперь снова могу.»; без фактов — коротко."""
    if span is None:
        return f"я молчал — {_OUTAGE_TAIL}"
    period = _period(span.since, span.until)
    duration = _duration(span.until - span.since)
    return f"я молчал {period} ({duration}): {_cause(span)}, {_OUTAGE_TAIL}"


def _cause(span: OutageSpan) -> str:
    """Причина простоя человеческими словами — с правильным говорящим."""
    speaker = _UNDERSTUDY if span.provider == _LOCAL_UNDERSTUDY else _CLOUD
    template = _CAUSE_BY_CLASS.get(span.failure_class or "", _CAUSE_UNKNOWN)
    return template.format(n=speaker.nominative, g=speaker.genitive, e=speaker.past_ending)


def _period(since: datetime, until: datetime) -> str:
    """«1 октября с 06:10 по 06:42» в пределах дня, иначе «с 1 октября 06:10 по …»."""
    if since.date() == until.date():
        return f"{_date(since, with_year=False)} с {_clock(since)} по {_clock(until)}"
    with_year = since.year != until.year
    start = f"{_date(since, with_year=with_year)} {_clock(since)}"
    end = f"{_date(until, with_year=with_year)} {_clock(until)}"
    preposition = "со" if since.day == _DAY_TAKING_SO else "с"
    return f"{preposition} {start} по {end}"


def _date(moment: datetime, *, with_year: bool) -> str:
    """«1 октября» или «31 декабря 2026»."""
    text = f"{moment.day} {_MONTHS_GENITIVE[moment.month - 1]}"
    return f"{text} {moment.year}" if with_year else text


def _clock(moment: datetime) -> str:
    """«06:10»."""
    return f"{moment.hour:02d}:{moment.minute:02d}"


def _duration(span: timedelta) -> str:
    """Длительность по-русски: старшая ненулевая единица и следующая, если она не ноль."""
    total_minutes = int(span.total_seconds()) // _SECONDS_PER_MINUTE
    hours, minutes = divmod(total_minutes, _MINUTES_PER_HOUR)
    days, hours = divmod(hours, _HOURS_PER_DAY)
    units = tuple(zip((days, hours, minutes), _UNIT_FORMS, strict=True))
    first = next((index for index, (count, _) in enumerate(units) if count), None)
    if first is None:
        return "меньше минуты"
    shown = [(count, forms) for count, forms in units[first : first + 2] if count]
    return " ".join(f"{count} {_plural(count, forms)}" for count, forms in shown)


def _plural(count: int, forms: tuple[str, str, str]) -> str:
    """Согласование с числительным: 1/21 день, 2/22 дня, 5/11/12 дней."""
    one, few, many = forms
    if count % _CENTURY in _TEENS:
        return many
    last = count % _DECIMAL
    if last == _LAST_DIGIT_ONE:
        return one
    if last in _FEW:
        return few
    return many


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
