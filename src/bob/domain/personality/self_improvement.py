# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Модель правила самоулучшения — чистый домен (BOB-028 .1).

Метакогнитивный слой: Боб замечает поведенческие паттерны за собой и формирует
человекочитаемое :class:`ImprovementRule` (наблюдение + поправка + рычаг из
жёсткого allowlist + ограниченная величина), которое owner одобряет, а
применение читает как мягкий обратимый наклон поведения. Здесь — только модель,
машина состояний и чистый выбор активных правил: ни I/O, ни LLM, ни часов,
детерминированно тестируемо.

ГРАНИЦА БЕЗОПАСНОСТИ ПО КОНСТРУКЦИИ (safety-инвариант, тесты .4 / ревью .5):
:class:`Lever` — жёсткий ALLOWLIST рычагов, которые правило вправе наклонять
(тон / длина / проактивность / адресность / юмор). У него НАМЕРЕННО НЕТ члена для
authz, гость-инварианта (BOB-019), ядра SOUL или safety-инвариантов автономии
(BOB-015) — поэтому правило НЕ способно их представить *по конструкции*, а не
лишь "по тестам". Это первый слой defense-in-depth; второй — применение (.3),
которое читает только этот allowlist.

ALLOWLIST состояний (authz-before-autonomy): детектор (.2) создаёт правило только
в ``PROPOSED``; переход ``PROPOSED -> APPROVED`` валиден на уровне домена, но его
ИНИЦИИРУЕТ исключительно owner-апрув на уровне use-case (.3). :func:`active_rules`
берёт лишь ``APPROVED`` — ни одно неодобренное или приостановленное правило не
влияет на поведение.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime  # noqa: TC003 — runtime-needed for the frozen field type
from difflib import SequenceMatcher
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

# Порог сходства наблюдений для дедупа кандидата против существующего правила
# (BOB-028 .2). Реюз бара анти-повтора BOB-026: консервативно высокий, чтобы
# ловить near-дубли (одна и та же мысль, переформулированная), но НЕ сливать
# два разных по сути наблюдения по одному рычагу.
_DEFAULT_DEDUP_THRESHOLD = 0.85

__all__ = [
    "ImprovementRule",
    "ImprovementSignals",
    "Lever",
    "RuleOrigin",
    "RuleState",
    "active_rules",
    "can_transition",
    "clamp_magnitude",
    "is_duplicate_rule",
    "rules_for_lever",
]


class Lever(StrEnum):
    """Жёсткий ALLOWLIST рычагов, которые правило вправе мягко наклонять.

    ``TONE`` (тон), ``LENGTH`` (длина ответа), ``PROACTIVITY`` (проактивность),
    ``ADDRESSIVITY_BIAS`` (байес адресности) и ``HUMOR`` (юмор) — И ТОЛЬКО ОНИ.

    НАМЕРЕННО НЕТ члена для authz, гость-инварианта, ядра SOUL или safety-
    инвариантов автономии: правило не может выбрать несуществующий рычаг, поэтому
    граница безопасности здесь КОНСТРУКТИВНА, а не держится на проверках. Это
    первый слой defense-in-depth (второй — применение в .3 читает только этот
    allowlist). Строковый ``Enum`` — значение кладётся прямо в SQLite TEXT-колонку.
    """

    TONE = "tone"
    LENGTH = "length"
    PROACTIVITY = "proactivity"
    ADDRESSIVITY_BIAS = "addressivity_bias"
    HUMOR = "humor"


class RuleState(StrEnum):
    """Состояние правила — машина жизненного цикла под owner-апрувом.

    ``PROPOSED`` (детектор предложил, ждёт owner-апрува) -> ``APPROVED`` (одобрено,
    влияет на поведение) <-> ``PAUSED`` (owner временно отключил, обратимо);
    ``PROPOSED`` -> ``REJECTED`` (owner отклонил, терминально); ``APPROVED`` /
    ``PAUSED`` -> ``REMOVED`` (owner убрал, терминально). Строковый ``Enum`` —
    значение кладётся прямо в SQLite TEXT-колонку.
    """

    PROPOSED = "proposed"
    APPROVED = "approved"
    PAUSED = "paused"
    REJECTED = "rejected"
    REMOVED = "removed"


class RuleOrigin(StrEnum):
    """Происхождение правила — кто его сформулировал.

    ``BOB_PROPOSED`` — Боб сам вывел правило из паттернов своей истории общения.
    Оставлено расширяемым (на будущее: owner мог бы предложить правило напрямую).
    """

    BOB_PROPOSED = "bob_proposed"


# Разрешённые переходы правила. PROPOSED->APPROVED только owner-апрувом (use-case
# .3); детектор (.2) создаёт лишь PROPOSED. REJECTED/REMOVED — терминальные.
_RULE_TRANSITIONS: dict[RuleState, frozenset[RuleState]] = {
    RuleState.PROPOSED: frozenset({RuleState.APPROVED, RuleState.REJECTED}),
    RuleState.APPROVED: frozenset({RuleState.PAUSED, RuleState.REMOVED}),
    RuleState.PAUSED: frozenset({RuleState.APPROVED, RuleState.REMOVED}),
    RuleState.REJECTED: frozenset(),
    RuleState.REMOVED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class ImprovementRule:
    """Правило-стратегия самоулучшения — что Боб заметил и какую поправку предлагает.

    ``observation`` — человекочитаемое наблюдение (рус): "что Боб заметил за
    собой". ``adjustment`` — какую поправку он предлагает. ``lever`` — рычаг из
    :class:`Lever`-allowlist, который правило наклоняет (и только он). ``magnitude``
    — величина мягкого наклона в ``[0, 1]`` (применение дополнительно клампит её к
    ``max_magnitude`` из конфига — это наклон, никогда не перехват). ``state`` —
    :class:`RuleState`. ``origin`` — :class:`RuleOrigin`. ``evidence`` — какие
    паттерны сработали (для прозрачности перед owner). ``frozen, slots``: без I/O,
    детерминированно, переиспользуемо стором и use-case'ами.
    """

    id: str
    observation: str
    adjustment: str
    lever: Lever
    magnitude: float
    state: RuleState
    origin: RuleOrigin
    created_at: datetime
    evidence: str


@dataclass(frozen=True, slots=True)
class ImprovementSignals:
    """Структурированный срез наблюдений Боба за собой — вход детектора (BOB-028 .2).

    Чистые данные: то, что use-case ``detect_patterns`` собирает из read-seam'ов
    (недавние эпизоды, mood_history, relationship/engagement) и передаёт детектору,
    чтобы тот сформулировал человечное правило. Поля — минимальный РЕАЛЬНО
    достижимый набор; каждый источник опционален, поэтому дефолты — «нет сигнала»
    (unwired seam -> пустые сигналы -> детектору нечего предлагать):

    * ``self_repeat_count`` — сколько раз сработал анти-повтор ответа Боба
      (BOB-026): Боб ловит себя на самоповторах.
    * ``addressivity_outcomes`` — счётчики исходов адресности
      (``SILENT`` / ``REACT`` / ``ENGAGE``, BOB-023/025): перекос к молчанию или к
      разговорчивости — кандидат на наклон ``ADDRESSIVITY_BIAS`` / ``PROACTIVITY``.
    * ``verbosity_misses`` — промахи длины-vs-спрос (BOB-024): ответ заметно
      длиннее/короче запрошенного — кандидат на ``LENGTH``.
    * ``relationship_deltas`` — дельты осей отношений (BOB-014, ``warmth`` и т.п.):
      проседание тепла — кандидат на ``TONE`` / ``HUMOR``.
    * ``mood_stuck`` / ``mood_stuck_tone`` — застряло ли настроение (valence/arousal
      вне окна базлайна дольше порога — из mood_history) и каким тоном: кандидат на
      ``TONE`` / ``PROACTIVITY``.
    * ``owner_friction`` — счётчик трения owner'а (повтор вопроса, «почему молчишь»):
      сигнал, что текущее поведение не попадает в ожидание.
    * ``positive_signals`` — что зашло (позитивные дельты: шутка сработала, тон
      попал): чтобы правило закрепляло удачное, а не только чинило неудачное.
    * ``recent_observations`` — короткий хвост недавних эпизодов как грундинг
      формулировки (детектор пишет наблюдение в реальном контексте, не в вакууме).

    ``frozen, slots``: без I/O, детерминированно, переиспользуемо детектором.
    """

    self_repeat_count: int = 0
    addressivity_outcomes: Mapping[str, int] = field(default_factory=dict)
    verbosity_misses: int = 0
    relationship_deltas: Mapping[str, float] = field(default_factory=dict)
    mood_stuck: bool = False
    mood_stuck_tone: str = ""
    owner_friction: int = 0
    positive_signals: tuple[str, ...] = ()
    recent_observations: tuple[str, ...] = ()


# «Живые» состояния для дедупа: новое предложение не должно блокироваться
# терминальным правилом (REJECTED/REMOVED — owner уже разобрался с тем правилом),
# но должно — любым ещё актуальным (PROPOSED ждёт апрува, APPROVED/PAUSED активно).
_LIVE_DEDUP_STATES: frozenset[RuleState] = frozenset(
    {RuleState.PROPOSED, RuleState.APPROVED, RuleState.PAUSED}
)


def can_transition(frm: RuleState, to: RuleState) -> bool:
    """Можно ли перевести правило из ``frm`` в ``to`` (чистый предикат).

    Самопереход (``frm == to``) переходом НЕ считается. Терминальные состояния
    (``REJECTED`` / ``REMOVED``) не имеют исходящих переходов. ``PROPOSED ->
    APPROVED`` валиден здесь, но его инициирует только owner-апрув (use-case .3).
    """
    return to in _RULE_TRANSITIONS[frm]


def active_rules(rules: Iterable[ImprovementRule]) -> tuple[ImprovementRule, ...]:
    """Вернуть только активные (``APPROVED``) правила, сохраняя порядок.

    Применение (.3) наклоняет поведение ИСКЛЮЧИТЕЛЬНО на основе этого результата:
    ``PROPOSED`` (ждёт апрува), ``PAUSED`` (owner отключил), ``REJECTED`` и
    ``REMOVED`` исключены — authz-before-autonomy держится здесь.
    """
    return tuple(rule for rule in rules if rule.state is RuleState.APPROVED)


def rules_for_lever(
    rules: Iterable[ImprovementRule], lever: Lever
) -> tuple[ImprovementRule, ...]:
    """Вернуть правила, наклоняющие ``lever`` (один рычаг — одна точка применения)."""
    return tuple(rule for rule in rules if rule.lever is lever)


def _normalise_observation(text: str) -> str:
    """Strip / casefold / collapse whitespace для сравнения наблюдений (как BOB-026)."""
    return " ".join(text.split()).casefold()


def is_duplicate_rule(
    candidate: ImprovementRule,
    existing: Iterable[ImprovementRule],
    *,
    threshold: float = _DEFAULT_DEDUP_THRESHOLD,
) -> bool:
    """Дублирует ли ``candidate`` какое-то «живое» правило (BOB-028 .2).

    Дубль = ТОТ ЖЕ рычаг И близкое наблюдение (один рычаг -> одна точка наклона,
    дважды чинить одно и то же незачем). Реюз идеи анти-повтора BOB-026: наблюдения
    нормализуются (strip / casefold / collapse whitespace) и сравниваются
    :class:`difflib.SequenceMatcher`; дубль, если совпадают дословно ИЛИ сходство
    не ниже ``threshold``. Сравнение только против «живых» правил
    (:data:`_LIVE_DEDUP_STATES`): отклонённое/убранное правило не блокирует новое
    предложение. Пустое ``candidate``-наблюдение дублем не считается.
    """
    normalised_candidate = _normalise_observation(candidate.observation)
    if not normalised_candidate:
        return False
    for rule in existing:
        if rule.state not in _LIVE_DEDUP_STATES or rule.lever is not candidate.lever:
            continue
        normalised_prior = _normalise_observation(rule.observation)
        if not normalised_prior:
            continue
        if normalised_candidate == normalised_prior:
            return True
        ratio = SequenceMatcher(None, normalised_candidate, normalised_prior).ratio()
        if ratio >= threshold:
            return True
    return False


def clamp_magnitude(value: float, *, cap: float) -> float:
    """Зажать величину наклона в ``[0, cap]`` (мягкий наклон, никогда не перехват).

    ``cap`` — потолок из конфига (``max_magnitude``, .3): он ограничивает суммарный
    дрейф поведения. Отрицательная величина обнуляется (наклон не инвертирует
    базовое поведение), величина выше потолка усекается до ``cap``.
    """
    return max(0.0, min(value, cap))
