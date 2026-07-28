# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Краткость по запросу — answer-demand + verbosity (BOB-024).

Длина реплики Боба перестаёт быть константой: чистый сигнал **answer-demand**
(сколько развёрнутости объективно требует само сообщение) объединяется с
**интересом** (BOB-014 .2a), **настроением/аппетитом** (BOB-020 / .2a) и мягким
:class:`~bob.personality.expression.FormHint` (BOB-018) в решение о
**многословии** (:class:`Verbosity`). Над этим в application собирается сильная
директива длины + few-shot (беад .2); здесь — только чистая логика.

* :class:`AnswerDemand` — LOW / MEDIUM / HIGH: сколько ответа требует сообщение.
* :func:`classify_answer_demand` — лёгкая лексическая эвристика (рус+eng) над
  текстом: детерминированная, без I/O, без рандома.
* :class:`Verbosity` — TERSE / NORMAL / EXPANSIVE: финальная развёрнутость хода.
* :class:`BrevityThresholds` — пороги тюнинга (инъекция из ``brevity.*`` конфига).
* :func:`decide_verbosity` — чистое решение по demand x интерес x настроение/
  аппетит, с form_hint-наклоном, seeded-апгрейдом по интересу и анти-обрубком
  для HIGH-demand owner. Детерминировано по явному ``roll`` — рандома внутри нет.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bob.personality.expression import FormHint, Verbosity

__all__ = [
    "AnswerDemand",
    "BrevityThresholds",
    "clamp_reply",
    "classify_answer_demand",
    "decide_verbosity",
]

# Sentence-ending marks the optional length guard trims on: the first finished
# thought up to (and including) one of these is kept; a reply with none is left
# whole (the guard is light — it never cuts mid-word).
_SENTENCE_ENDINGS = (".", "?", "!", "…")

# --- answer-demand: словари и пороги эвристики --------------------------------
# Кириллические литералы намеренны: эвристика матчит реальный русский текст.

# Открытые вопросительные слова: ведут к развёрнутому ответу (HIGH). Берём как
# подстроки в нижнем регистре. "что думаешь" / "в чём разница" — устойчивые
# открытые обороты; одиночное "что"/"what" слишком шумно, поэтому не берём его
# в одиночку.
_OPEN_QUESTION_MARKERS: tuple[str, ...] = (
    "почему",
    "зачем",
    "как так",
    "как это",
    "как ты",
    "что думаешь",
    "как думаешь",
    "в чём разниц",
    "в чем разниц",
    "what do you think",
    "how does",
    "how do",
    "why ",
)

# Явные просьбы развернуть/объяснить — сильный сигнал HIGH вне зависимости от "?".
_ELABORATION_MARKERS: tuple[str, ...] = (
    "расскажи",
    "объясни",
    "сравни",
    "подробнее",
    "разверни",
    "поясни",
    "опиши",
    "tell me about",
    "explain",
    "compare",
    "elaborate",
    "describe",
)

# Слова, открывающие закрытый/уточняющий вопрос (да/нет, «во сколько», «получилось»):
# короткий ожидаемый ответ → LOW.
_CLOSED_QUESTION_MARKERS: tuple[str, ...] = (
    "во сколько",
    "получилось",
    "получилась",
    "успел",
    "ты тут",
    "ты здесь",
    "правда ли",
    "did it",
    "are you",
    "is it",
    "was it",
    "do you have",
)

# Текст не длиннее этого (символов, после strip) — короткая реплика: при наличии
# вопроса читается как закрытый (LOW), без вопроса — короткая болтовня (LOW).
_SHORT_TEXT_CHARS = 16

# Не больше этого числа слов — короткий закрытый вопрос (LOW), если в нём нет
# открытых маркеров развёрнутости.
_SHORT_QUESTION_WORDS = 4

# Столько и более знаков "?" — много-частный вопрос (несколько вопросов разом) → HIGH.
_MULTIPART_QUESTION_MARKS = 2


class AnswerDemand(Enum):
    """Сколько развёрнутости объективно требует сообщение (perception, не решение).

    * :data:`LOW` — закрытый/простой вопрос или короткая реплика: да/нет,
      «ты тут?», «во сколько?», подтверждение/факт-чек, очень короткий текст.
    * :data:`HIGH` — открытый/глубокий запрос: «почему/как/что думаешь», явные
      «расскажи/объясни/сравни», много-частный вопрос, просьба мнения.
    * :data:`MEDIUM` — всё прочее (обычная реплика без явного сигнала).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# Порядок ступеней снизу вверх — для апгрейда/даун-шифта с клиппингом по краям.
_VERBOSITY_LADDER: tuple[Verbosity, ...] = (
    Verbosity.TERSE,
    Verbosity.NORMAL,
    Verbosity.EXPANSIVE,
)

# База: demand → стартовая ступень.
_DEMAND_BASE: dict[AnswerDemand, Verbosity] = {
    AnswerDemand.LOW: Verbosity.TERSE,
    AnswerDemand.MEDIUM: Verbosity.NORMAL,
    AnswerDemand.HIGH: Verbosity.EXPANSIVE,
}

# Частоты/пороги — вероятности в замкнутом единичном интервале.
_MIN_FREQ = 0.0
_MAX_FREQ = 1.0

# Дефолты тюнинга (консервативны). Высокий порог интереса для апгрейда, малая
# seeded-частота апгрейда, пороги даун-шифта по настроению/аппетиту.
_DEFAULT_INTEREST_UPGRADE = 0.85
_DEFAULT_UPGRADE_FREQ = 0.1
_DEFAULT_BAD_MOOD = -0.5
_DEFAULT_LOW_ENGAGEMENT = 0.25
# Мягко-плохое настроение: само по себе не урезает, но в паре с TERSE form_hint
# даёт наклон вниз (form_hint усиливает, а не задаёт).
_DEFAULT_TILT_MOOD = -0.25


def classify_answer_demand(*, text: str | None) -> AnswerDemand:
    """Определить answer-demand по тексту — чисто, детерминированно (BOB-024).

    Лёгкая лексическая эвристика (рус+eng) без I/O и без рандома. Приоритет
    сигналов (сильный → слабый):

    1. **HIGH** — явная просьба развернуть («расскажи/объясни/сравни», tell me
       about/explain) ИЛИ открытое вопросительное слово («почему/как это/что
       думаешь», why/how does) ИЛИ много-частный вопрос (несколько «?»).
    2. **LOW** — закрытый/короткий вопрос: маркер закрытого вопроса («во сколько»,
       «получилось», are you), ИЛИ короткий вопрос (мало слов, нет открытых
       маркеров), ИЛИ очень короткая реплика без вопроса.
    3. **MEDIUM** — всё прочее. Пустой/``None`` текст → MEDIUM (без падений).
    """
    if text is None:
        return AnswerDemand.MEDIUM
    stripped = text.strip()
    if not stripped:
        return AnswerDemand.MEDIUM

    lowered = stripped.casefold()
    if _is_high_demand(lowered):
        return AnswerDemand.HIGH
    if _is_low_demand(lowered, stripped):
        return AnswerDemand.LOW
    return AnswerDemand.MEDIUM


def _is_high_demand(lowered: str) -> bool:
    """Открытый/глубокий запрос: просьба развернуть, открытый вопрос или много-частный."""
    if _contains_any(lowered, _ELABORATION_MARKERS):
        return True
    if _contains_any(lowered, _OPEN_QUESTION_MARKERS):
        return True
    return lowered.count("?") >= _MULTIPART_QUESTION_MARKS


def _is_low_demand(lowered: str, stripped: str) -> bool:
    """Закрытый/короткий вопрос или очень короткая реплика (нет открытых маркеров)."""
    if _contains_any(lowered, _CLOSED_QUESTION_MARKERS):
        return True
    has_question = "?" in stripped
    if has_question and _word_count(stripped) <= _SHORT_QUESTION_WORDS:
        return True
    return len(stripped) <= _SHORT_TEXT_CHARS


def _contains_any(lowered: str, markers: tuple[str, ...]) -> bool:
    """Есть ли в тексте (нижний регистр) хоть один маркер-подстрока."""
    return any(marker in lowered for marker in markers)


def _word_count(text: str) -> int:
    """Число слов (грубо, по пробелам) — для эвристики короткого вопроса."""
    return len(text.split())


@dataclass(frozen=True, slots=True)
class BrevityThresholds:
    """Пороги тюнинга многословия (инъекция из ``brevity.*`` конфига).

    Дефолты консервативны — Боб редко разворачивается «от интереса» и урезает
    только при заметно плохом настроении / низком аппетите.

    * ``interest_upgrade`` — высокий порог интереса, при котором ход может
      подняться на ступень «от увлечённости» (US-4).
    * ``upgrade_freq`` — малая seeded-частота такого апгрейда (вероятность в
      ``[0, 1]``): апгрейд изредка, не монолог.
    * ``bad_mood`` — порог валентности настroения (``[-1, 1]``): при значении
      НИЖЕ него ход урезается на ступень (US-3).
    * ``low_engagement`` — порог аппетита (``[0, 1]``): при значении НИЖЕ него
      ход урезается на ступень (US-3, BOB-014 .2a TERSE/DECLINE).
    * ``tilt_mood`` — мягкий порог настроения для form_hint-наклона: при
      настроении ниже него TERSE form_hint добавляет даун-шифт (form_hint
      усиливает наклон, но не задаёт его в одиночку).
    """

    interest_upgrade: float = _DEFAULT_INTEREST_UPGRADE
    upgrade_freq: float = _DEFAULT_UPGRADE_FREQ
    bad_mood: float = _DEFAULT_BAD_MOOD
    low_engagement: float = _DEFAULT_LOW_ENGAGEMENT
    tilt_mood: float = _DEFAULT_TILT_MOOD

    def __post_init__(self) -> None:
        if not _MIN_FREQ <= self.upgrade_freq <= _MAX_FREQ:
            raise ValueError(
                f"brevity threshold 'upgrade_freq' must be within "
                f"[{_MIN_FREQ}, {_MAX_FREQ}], got {self.upgrade_freq}"
            )


def decide_verbosity(
    *,
    demand: AnswerDemand,
    interest: float,
    mood_valence: float,
    engagement: float,
    form_hint: FormHint,
    roll: float,
    is_owner: bool,
    thresholds: BrevityThresholds | None = None,
) -> Verbosity:
    """Решить многословие хода — чисто, детерминированно по ``roll`` (BOB-024).

    ``roll`` — одна seeded-проба в ``[0, 1)`` (инъектируется application'ом из
    общего RNG, чтобы ход воспроизводился). Порядок применения:

    1. **База** — ``demand`` задаёт стартовую ступень (LOW→TERSE, MEDIUM→NORMAL,
       HIGH→EXPANSIVE). Это основа; form_hint её сам по себе не перебивает.
    2. **Интерес↑ (US-4)** — при ``interest >= thresholds.interest_upgrade`` И
       редком ``roll < thresholds.upgrade_freq`` ступень поднимается на одну
       (с клиппингом по EXPANSIVE): изредка, seeded, «увлёкся».
    3. **Настроение/аппетит↓ (US-3)** — при плохом ``mood_valence`` (ниже
       ``bad_mood``) и/или низком ``engagement`` (ниже ``low_engagement``)
       ступень опускается на одну (детерминированно). ``form_hint`` TERSE при
       мягко-плохом настроении (ниже ``tilt_mood``) добавляет тот же наклон вниз
       — мягкий вход, усиливающий настроение, а не отдельная директива.
    4. **Анти-обрубок (US-5)** — если ``demand == HIGH`` и ``is_owner``, итог не
       опускается ниже NORMAL, что бы ни говорили настроение/аппетит: прямой
       содержательный запрос owner не получает односложный «отшив».

    ``is_owner`` — примитив (владелец ли собеседник); домен не зависит от
    инфраструктуры Trust/engagement, application прокидывает готовый флаг.
    """
    bands = thresholds if thresholds is not None else BrevityThresholds()
    level = _DEMAND_BASE[demand]
    level = _apply_interest_upgrade(level, interest=interest, roll=roll, bands=bands)
    level = _apply_downshift(
        level,
        mood_valence=mood_valence,
        engagement=engagement,
        form_hint=form_hint,
        bands=bands,
    )
    if demand is AnswerDemand.HIGH and is_owner:
        level = _at_least(level, Verbosity.NORMAL)
    return level


def _apply_interest_upgrade(
    level: Verbosity, *, interest: float, roll: float, bands: BrevityThresholds
) -> Verbosity:
    """Поднять ступень при высоком интересе и редком удачном ``roll`` (US-4)."""
    if interest >= bands.interest_upgrade and roll < bands.upgrade_freq:
        return _step(level, +1)
    return level


def _apply_downshift(
    level: Verbosity,
    *,
    mood_valence: float,
    engagement: float,
    form_hint: FormHint,
    bands: BrevityThresholds,
) -> Verbosity:
    """Опустить ступень за каждый наклон вниз (настроение/аппетит/TERSE-наклон) (US-3).

    Наклоны складываются: заметно плохое настроение И низкий аппетит вместе
    режут на ДВЕ ступени (с клиппингом по TERSE) — содержательный ход «отшивается»
    сильнее, чем при одном плохом сигнале. TERSE form_hint при мягко-плохом
    настроении даёт ещё один наклон (усиливает, не задаёт в одиночку).
    """
    steps = _downshift_steps(
        mood_valence=mood_valence,
        engagement=engagement,
        form_hint=form_hint,
        bands=bands,
    )
    return _step(level, -steps)


def _downshift_steps(
    *,
    mood_valence: float,
    engagement: float,
    form_hint: FormHint,
    bands: BrevityThresholds,
) -> int:
    """Сколько ступеней вниз: по одной за плохое настроение, низкий аппетит, TERSE-наклон."""
    steps = 0
    if mood_valence < bands.bad_mood:
        steps += 1
    if engagement < bands.low_engagement:
        steps += 1
    # TERSE form_hint при мягко-плохом настроении добавляет наклон, но не дублирует
    # уже учтённое «плохое настроение» (иначе один сигнал считался бы дважды).
    soft_bad_mood = bands.bad_mood <= mood_valence < bands.tilt_mood
    if form_hint is FormHint.TERSE and soft_bad_mood:
        steps += 1
    return steps


def _step(level: Verbosity, delta: int) -> Verbosity:
    """Сдвинуть ступень на ``delta`` с клиппингом по краям лестницы."""
    index = _VERBOSITY_LADDER.index(level)
    clamped = max(0, min(len(_VERBOSITY_LADDER) - 1, index + delta))
    return _VERBOSITY_LADDER[clamped]


def _at_least(level: Verbosity, floor: Verbosity) -> Verbosity:
    """Не ниже ``floor`` на лестнице (анти-обрубок)."""
    if _VERBOSITY_LADDER.index(level) < _VERBOSITY_LADDER.index(floor):
        return floor
    return level


def clamp_reply(text: str, *, max_chars: int) -> str:
    """Лёгкое ужатие переразвёрнутого ответа до первой мысли — чисто (BOB-024).

    Опциональный страж длины (за флагом ``brevity.length_guard.enabled``, выкл по
    умолчанию): когда ответ на простой вопрос вышел длиннее ``max_chars``, берём
    первую законченную мысль — текст до первого знака конца предложения
    (``. ? ! …``) включительно — БЕЗ перегенерации и БЕЗ обрезки на полуслове.
    Страховка, а не основной рычаг (тот — байес директивы + few-shot).

    Не трогаем текст, если он уже в пределах ``max_chars`` или если в нём нет ни
    одного знака конца предложения (рубить по предложению нечего — отдаём как есть,
    чтобы не обрубать мысль на полуслове). Чисто и детерминировано.
    """
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return text
    cut = _first_sentence_end(stripped)
    if cut is None:
        return text
    return stripped[: cut + 1]


def _first_sentence_end(text: str) -> int | None:
    """Индекс первого знака конца предложения (``. ? ! …``), или ``None``."""
    positions = [text.find(mark) for mark in _SENTENCE_ENDINGS]
    found = [index for index in positions if index >= 0]
    return min(found) if found else None
