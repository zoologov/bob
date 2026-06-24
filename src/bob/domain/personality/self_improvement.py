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
    "RuleModulators",
    "RuleOrigin",
    "RuleState",
    "active_rules",
    "build_modulators",
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


# --- Мягкое применение: сборка модуляторов из active_rules (BOB-028 .3) -------

# Порог суммарной (заклампленной) LENGTH-величины, выше которого правило сдвигает
# многословие на ОДНУ ступень. Ниже порога — наклона нет (микро-правило не дёргает
# длину). Один шаг и только один — это наклон, а не перехват: лестница многословия
# (TERSE/NORMAL/EXPANSIVE) не переворачивается, край клиппится приёмником.
_LENGTH_STEP_THRESHOLD = 0.05

# Консервативное направление LENGTH-наклона: к КОРОЧЕ (-1). Север-звезда Боба —
# краткость по запросу (BOB-024); правило-самоулучшение про длину почти всегда
# означает «я слишком многословен». Рычаг сам по себе направления не несёт
# (magnitude в [0, 1]), поэтому направление фиксировано и безопасно: один шаг вниз,
# никогда не раздувание ответа.
_LENGTH_STEP_DIRECTION = -1


@dataclass(frozen=True, slots=True)
class RuleModulators:
    """Набор мягких наклонов, собранных из ``active_rules`` — каждый в свою точку.

    Каждое поле — отдельный рычаг :class:`Lever`, который применяется В СВОЕЙ точке
    поведения (один рычаг → одна точка, без перекрёстных эффектов):

    * ``voice_adjustments`` — человекочитаемые поправки ТОНА / ЮМОРА (``adjustment``
      одобренных TONE/HUMOR-правил), которые ``voice.improvement_directive`` оборачивает
      в наклон-голоса для ``_system_prompt_for``. Пустой кортеж → ничего не добавляется
      (прозу владеет voice — домен отдаёт только данные).
    * ``length_step`` — целочисленный сдвиг ступени многословия (BOB-024): ``-1``
      короче, ``0`` без сдвига. Не больше одной ступени — мягкий наклон, не перехват;
      приёмник клиппит по краям лестницы.
    * ``proactivity_bias`` — байес к urge/governance (BOB-010) в ``[0, max_magnitude]``.
    * ``addressivity_bias`` — байес к порогам адресности (BOB-023/025) в
      ``[0, max_magnitude]``.

    Все величины уже закламплены к ``max_magnitude`` сборщиком. Дефолт (все поля
    нейтральны) — это «нет применения»: поведение ровно как до BOB-028.
    """

    voice_adjustments: tuple[str, ...] = ()
    length_step: int = 0
    proactivity_bias: float = 0.0
    addressivity_bias: float = 0.0

    def has_any(self) -> bool:
        """Есть ли хоть один ненулевой наклон (иначе применять нечего)."""
        return bool(
            self.voice_adjustments
            or self.length_step
            or self.proactivity_bias
            or self.addressivity_bias
        )


def _summed_clamped(
    rules: Iterable[ImprovementRule], lever: Lever, *, cap: float
) -> float:
    """Суммарная величина правил рычага ``lever``, зажатая в ``[0, cap]``.

    Несколько правил по одному рычагу складываются, но суммарный наклон НЕ
    превышает ``cap`` — суммарный дрейф ограничен (число правил ограничивает
    ``max_active_rules`` на стороне детектора/применения, величину — этот кламп).
    """
    total = sum(rule.magnitude for rule in rules if rule.lever is lever)
    return clamp_magnitude(total, cap=cap)


def _voice_adjustments_for(rules: Iterable[ImprovementRule]) -> tuple[str, ...]:
    """Поправки ГОЛОСА из TONE/HUMOR-правил — человекочитаемый ``adjustment`` каждого.

    Берёт непустой ``adjustment`` каждого APPROVED TONE/HUMOR-правила (без рычага —
    пусто). Прозу из них лепит ``voice.improvement_directive`` — домен отдаёт лишь
    грундированные данные (поправки реальны, не выдуманы).
    """
    return tuple(
        rule.adjustment.strip()
        for rule in rules
        if rule.lever in _VOICE_LEVERS and rule.adjustment.strip()
    )


# Рычаги, наклоняющие ГОЛОС (тон/юмор) — обе наклоняют одну точку (voice-директиву).
_VOICE_LEVERS: frozenset[Lever] = frozenset({Lever.TONE, Lever.HUMOR})


def build_modulators(
    rules: Iterable[ImprovementRule], *, max_magnitude: float
) -> RuleModulators:
    """Собрать мягкие модуляторы из ``rules`` — каждый рычаг в свою точку (BOB-028 .3).

    Safety-инварианты ПО КОНСТРУКЦИИ (defense-in-depth, второй слой над доменом):

    1. Применяются ТОЛЬКО ``APPROVED`` правила (через :func:`active_rules`):
       ``PROPOSED`` ждёт апрува, ``PAUSED`` отключено, ``REJECTED``/``REMOVED``
       терминальны — ни одно не наклоняет поведение (authz-before-autonomy).
    2. Читается ТОЛЬКО :class:`Lever`-allowlist: каждый рычаг сопоставлен своей
       точке (TONE/HUMOR → голос, LENGTH → многословие, PROACTIVITY → urge,
       ADDRESSIVITY_BIAS → пороги адресности). authz/гость/SOUL/safety не имеют
       рычага → их нельзя наклонить (граница безопасности конструктивна).
    3. Наклон, НЕ перехват: величины клампятся к ``max_magnitude``; LENGTH сдвигает
       не больше одной ступени и только к короче (не раздувает ответ). Суммарный
       дрейф по рычагу зажат потолком.

    Пустой ``rules`` или ни одного APPROVED → нейтральные :class:`RuleModulators`
    (поведение ровно как до BOB-028).
    """
    approved = active_rules(rules)
    if not approved:
        return RuleModulators()
    length_magnitude = _summed_clamped(approved, Lever.LENGTH, cap=max_magnitude)
    length_step = (
        _LENGTH_STEP_DIRECTION if length_magnitude > _LENGTH_STEP_THRESHOLD else 0
    )
    return RuleModulators(
        voice_adjustments=_voice_adjustments_for(approved),
        length_step=length_step,
        proactivity_bias=_summed_clamped(approved, Lever.PROACTIVITY, cap=max_magnitude),
        addressivity_bias=_summed_clamped(
            approved, Lever.ADDRESSIVITY_BIAS, cap=max_magnitude
        ),
    )
