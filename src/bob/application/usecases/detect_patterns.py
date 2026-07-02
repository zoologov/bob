# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""LlmPatternDetector + DetectPatterns — метакогнитивный детектор паттернов (BOB-028 .2).

Две части, обе чисто-оркестрационные (домен остаётся I/O-free):

* :class:`LlmPatternDetector` реализует порт :class:`bob.domain.ports.PatternDetector`:
  просит LLM (``TaskType.DETECT_PATTERNS``) по срезу :class:`ImprovementSignals`
  сформулировать человечные правила-кандидаты и парсит СТРОГИЙ JSON так же
  устойчиво, как извлечение фактов / планировщик (markdown-fence / преамбула / мусор
  по краям терпятся). КАЖДЫЙ кандидат жёстко нормализуется доменом: ``state``
  принудительно ``PROPOSED``, ``origin`` — ``BOB_PROPOSED``, ``lever`` берётся ТОЛЬКО
  из :class:`Lever`-allowlist (элемент с рычагом вне allowlist отбрасывается —
  граница безопасности по конструкции), ``magnitude`` клампится в ``[0, 1]``. Не-JSON
  / ошибка провайдера / мусор → ПУСТОЙ список (best-effort, без падения). Детектор
  НИЧЕГО не применяет — только предлагает (применение — .3).

* :class:`DetectPatterns` — use-case, который ReflectTick-seam драйвит на редком
  кадэнсе: собрать сигналы (опц. :class:`SignalSource`; unwired → пустые сигналы) →
  :meth:`PatternDetector.detect` → ДЕДУП против существующих правил (рычаг + близость
  наблюдения, реюз идеи анти-повтора BOB-026) → сохранить НОВЫХ кандидатов в
  ``PROPOSED`` через ``save_rule``. Лимит ``max_active_rules`` не даёт плодить
  правила (учитываются уже «живые», включая PROPOSED). НИКАКОГО применения и НИКАКИХ
  owner-команд здесь — только предложение кандидатов.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.domain.personality.self_improvement import (
    ImprovementRule,
    ImprovementSignals,
    Lever,
    RuleOrigin,
    RuleState,
    clamp_magnitude,
    is_duplicate_rule,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.router.llm_router import LLMRouter
    from bob.domain.personality.self_improvement import RuleState as _RuleStateT
    from bob.domain.ports import Clock, PatternDetector

logger = logging.getLogger(__name__)

__all__ = [
    "DetectPatterns",
    "LlmPatternDetector",
    "SignalSource",
]

# Потолок величины наклона на стороне детектора. Домен/применение (.3) клампят к
# конфиг-потолку ``max_magnitude`` ещё раз; здесь — ровно единичный диапазон правила.
_MAGNITUDE_CAP = 1.0

# Консервативный дефолт предела числа «живых» правил (PROPOSED+APPROVED+PAUSED),
# чтобы детектор не заваливал owner'а кандидатами. Перекрывается из конфига (.3).
_DEFAULT_MAX_ACTIVE_RULES = 5

# Рычаги, доступные правилу — строго из доменного allowlist (граница безопасности
# по конструкции: рычага для authz/гостя/SOUL/safety тут нет, поэтому правило их
# не представит). Карта строка→Lever для разбора ответа модели.
_LEVERS_BY_VALUE: dict[str, Lever] = {lever.value: lever for lever in Lever}

_LEVER_LIST = ", ".join(lever.value for lever in Lever)

_SYSTEM_PROMPT = (
    "Ты помогаешь Бобу замечать поведенческие паттерны за собой и формулировать "
    "человечные правила-поправки. По переданным сигналам о себе предложи правила. "
    "Ответь ТОЛЬКО JSON-массивом объектов, каждый вида "
    '{"observation": "<что Боб заметил за собой, по-русски>", '
    '"adjustment": "<какую мягкую поправку он предлагает>", '
    f'"lever": "<рычаг ТОЛЬКО из набора: {_LEVER_LIST}>", '
    '"magnitude": <число от 0 до 1 — насколько сильно наклонить>, '
    '"evidence": "<какие сигналы сработали>"}. '
    "Рычаг ОБЯЗАТЕЛЬНО из этого набора и НИКАКОЙ другой. magnitude — мягкий наклон, "
    "не перехват. Если внятных паттернов нет — ответь []."
)


class _DetectorRouter(Protocol):
    """The router surface the detector needs: run a request, return raw text."""

    async def run(self, request: LLMRequest) -> str: ...


class SignalSource(Protocol):
    """The narrow read seam DetectPatterns собирает сигналы из (BOB-028 .2).

    Реализуется application-адаптером (.3), который читает узкие read-seam'ы —
    недавние эпизоды, mood_history (застревание настроения), relationship /
    engagement — и складывает их в :class:`ImprovementSignals`. Опционален: unwired,
    use-case работает на пустых сигналах (детектору нечего предлагать), то есть
    поведение ровно как до BOB-028.
    """

    async def collect(self) -> ImprovementSignals:
        """Собрать текущий срез наблюдений Боба за собой (пустой, если нет данных)."""
        ...


class _SelfImprovementStoreLike(Protocol):
    """The SelfImprovementStore surface DetectPatterns needs (load + save_rule)."""

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]: ...
    async def save_rule(self, persona_id: str, rule: ImprovementRule) -> None: ...


class LlmPatternDetector:
    """Детектор паттернов через LLM (порт :class:`PatternDetector`)."""

    def __init__(self, *, router: LLMRouter | _DetectorRouter, clock: Clock) -> None:
        self._router = router
        self._clock = clock

    async def detect(self, signals: ImprovementSignals) -> Sequence[ImprovementRule]:
        """Вернуть правила-кандидаты в ``PROPOSED`` (пусто, если паттернов нет).

        Best-effort: ошибка провайдера или непарсимый ответ дают ПУСТОЙ список,
        а не исключение — детектор лишь предлагает, ничего не ломая в тике.
        """
        try:
            raw = await self._ask(signals)
        except Exception:
            logger.exception("Pattern detection failed; no candidates (best-effort)")
            return ()
        return self._to_rules(_parse_candidates(raw))

    async def _ask(self, signals: ImprovementSignals) -> str:
        request = LLMRequest(
            task_type=TaskType.DETECT_PATTERNS,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _render_signals(signals)},
            ],
        )
        return await self._router.run(request)

    def _to_rules(
        self, items: list[tuple[str, str, Lever, float, str]]
    ) -> tuple[ImprovementRule, ...]:
        """Собрать доменные правила из разобранных элементов (всегда PROPOSED).

        Жёсткая нормализация безопасности: ``state=PROPOSED`` и
        ``origin=BOB_PROPOSED`` ставятся ТУТ (модель не может выбрать иное),
        ``magnitude`` клампится в ``[0, 1]``, ``id`` генерируется детерминированно
        по моменту + индексу (модель не задаёт id).
        """
        now = self._clock.now()
        stamp = now.strftime("%Y%m%d%H%M%S")
        rules: list[ImprovementRule] = []
        for index, (observation, adjustment, lever, magnitude, evidence) in enumerate(items):
            rules.append(
                ImprovementRule(
                    id=f"rule-{stamp}-{index}",
                    observation=observation,
                    adjustment=adjustment,
                    lever=lever,
                    magnitude=clamp_magnitude(magnitude, cap=_MAGNITUDE_CAP),
                    state=RuleState.PROPOSED,
                    origin=RuleOrigin.BOB_PROPOSED,
                    created_at=now,
                    evidence=evidence,
                )
            )
        return tuple(rules)


class DetectPatterns:
    """Собрать сигналы → детектор → дедуп → сохранить кандидатов в PROPOSED.

    НИЧЕГО не применяет и не трогает owner-команды (это .3): use-case только
    предлагает правила, оставляя их в ``PROPOSED`` до owner-апрува.
    """

    def __init__(
        self,
        *,
        detector: PatternDetector | _DetectorLike,
        store: _SelfImprovementStoreLike,
        persona_id: str,
        signal_source: SignalSource | None = None,
        max_active_rules: int = _DEFAULT_MAX_ACTIVE_RULES,
    ) -> None:
        self._detector = detector
        self._store = store
        self._persona_id = persona_id
        self._signal_source = signal_source
        self._max_active_rules = max_active_rules

    async def run(self) -> None:
        """Один проход детектора: сигналы → кандидаты → дедуп → персист (PROPOSED).

        Уже «живых» правил (PROPOSED/APPROVED/PAUSED) не больше лимита — иначе ничего
        не добавляем (не плодим). Каждый сохранённый кандидат уникален по (рычаг +
        близость наблюдения) и против существующих, и внутри пачки. Никогда не
        применяет правило — только ``save_rule`` в ``PROPOSED``.
        """
        signals = await self._collect_signals()
        candidates = await self._detector.detect(signals)
        existing = await self._store.load(self._persona_id)
        live = [rule for rule in existing if rule.state in _LIVE_STATES]
        kept: list[ImprovementRule] = []
        for candidate in candidates:
            if len(live) + len(kept) >= self._max_active_rules:
                break
            if is_duplicate_rule(candidate, (*existing, *kept)):
                continue
            kept.append(candidate)
        for rule in kept:
            await self._store.save_rule(self._persona_id, rule)

    async def _collect_signals(self) -> ImprovementSignals:
        """Собрать сигналы из seam'а (unwired → пустые: детектору нечего предлагать)."""
        if self._signal_source is None:
            return ImprovementSignals()
        return await self._signal_source.collect()


class _DetectorLike(Protocol):
    """Structural PatternDetector surface (so a fake satisfies DetectPatterns)."""

    async def detect(self, signals: ImprovementSignals) -> Sequence[ImprovementRule]: ...


# «Живые» состояния, считающиеся в лимит: PROPOSED ждёт апрува, APPROVED/PAUSED
# активны; REJECTED/REMOVED — терминальны и в лимит не входят.
_LIVE_STATES: frozenset[_RuleStateT] = frozenset(
    {RuleState.PROPOSED, RuleState.APPROVED, RuleState.PAUSED}
)


def _render_signals(signals: ImprovementSignals) -> str:
    """Render the self-signals slice the detector reads (compact, human-readable)."""
    lines = [
        f"Срабатываний анти-повтора (самоповторы): {signals.self_repeat_count}",
        f"Исходы адресности: {dict(signals.addressivity_outcomes)}",
        f"Промахи длины-vs-спрос: {signals.verbosity_misses}",
        f"Дельты отношений: {dict(signals.relationship_deltas)}",
        f"Застряло ли настроение: {signals.mood_stuck} (тон: {signals.mood_stuck_tone})",
        f"Трение owner'а (повтор вопроса/«почему»): {signals.owner_friction}",
        f"Что зашло (позитивные дельты): {list(signals.positive_signals)}",
    ]
    if signals.recent_observations:
        lines.append("Недавние эпизоды: " + " | ".join(signals.recent_observations))
    return "\n".join(lines)


# --- JSON parsing (tolerant, mirrors fact extraction / planner) ---------------

# Markdown code fence, optionally tagged (``` or ```json), capturing its body.
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)


def _strip_code_fence(raw: str) -> str:
    """Return the body of the first markdown code fence, or ``raw`` unchanged."""
    match = _FENCE_RE.search(raw)
    return match.group(1) if match else raw


def _first_json_array(text: str) -> str | None:
    """Extract the first balanced ``[...]`` substring, or ``None`` (string-aware)."""
    start = text.find("[")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _decode_array(raw: str) -> list[object] | None:
    """Decode ``raw`` into a JSON list, recovering from reasoning-model wrapping."""
    candidates = [raw, _strip_code_fence(raw)]
    array = _first_json_array(raw)
    if array is not None:
        candidates.append(array)
    for candidate in candidates:
        try:
            decoded = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(decoded, list):
            return decoded
    return None


def _parse_candidates(raw: str) -> list[tuple[str, str, Lever, float, str]]:
    """Parse the model's JSON array into ``(observation, adjustment, lever, mag, ev)``.

    Tolerant (best-effort): markdown fences / a reasoning preamble / trailing text are
    stripped first. Граница безопасности: рычаг ОБЯЗАН быть из :class:`Lever`-allowlist
    — иначе элемент отбрасывается (правило с рычагом вне allowlist не существует).
    Отсутствие/пустота наблюдения, отсутствие/невалидный рычаг → элемент пропускается.
    ``magnitude`` приводится к числу (нечисло → 0.0; клампится позже).
    """
    decoded = _decode_array(raw)
    if decoded is None:
        logger.debug("Pattern detection returned no parseable JSON array; no candidates")
        return []
    items: list[tuple[str, str, Lever, float, str]] = []
    for entry in decoded:
        if not isinstance(entry, dict):
            continue
        observation = entry.get("observation")
        if not isinstance(observation, str) or not observation.strip():
            continue
        lever = _parse_lever(entry.get("lever"))
        if lever is None:
            continue
        adjustment = entry.get("adjustment")
        evidence = entry.get("evidence")
        items.append(
            (
                observation.strip(),
                adjustment.strip() if isinstance(adjustment, str) else "",
                lever,
                _parse_magnitude(entry.get("magnitude")),
                evidence.strip() if isinstance(evidence, str) else "",
            )
        )
    return items


def _parse_lever(raw: object) -> Lever | None:
    """Resolve a Lever from the model's value — ONLY a member of the allowlist.

    Граница безопасности по конструкции: значение вне :class:`Lever`-allowlist
    (попытка тронуть authz/гостя/SOUL/safety) не резолвится — кандидат отбрасывается.
    """
    if not isinstance(raw, str):
        return None
    return _LEVERS_BY_VALUE.get(raw.strip().casefold())


def _parse_magnitude(raw: object) -> float:
    """Parse ``magnitude`` into a float (non-numeric → 0.0; clamped by the caller)."""
    if isinstance(raw, bool):
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw.strip())
        except ValueError:
            return 0.0
    return 0.0
