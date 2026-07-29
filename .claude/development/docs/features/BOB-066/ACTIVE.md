<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: bob-vol.12.1 — Срез W.1-dev (rhythm consumption wiring)

## Фокус
Пласт 3 RFC: вшить УЖЕ построенные (в main) ритм-механизмы presence/ в hot-path
за флагом `presence.rhythm` (OFF=byte-identical). Коллабораторы, не толстить handle()/gate().

## План (TDD)
- [ ] reply_rhythm.py — чистый `reply_delay_inputs(demand, interest) -> (complexity, urgency)` [mutation ядро]
- [ ] TurnGate: опц. `barge_ceiling` (Protocol) — потолок на periphery-REPLY барж; фокус минует (INV-1); OFF=нет жребия
- [ ] ProactivityEngine: опц. `share_ceiling` — домножение проактив-файра на share-of-voice (throttle до LLM)
- [ ] HandleMessage: опц. `reply_delay` (DelayedTurn) оборачивает генерацию внутри typing (INV-9); + прокидывает barge_ceiling в TurnGate
- [ ] composition: `build_rhythm_wiring` (runtime/wiring/rhythm.py) за `presence.rhythm`; store=EpisodicOutgoingActivityStore(memory_repo); ОДИН ShareOfVoiceGate → barge+share; DelayedTurn(asyncio.sleep, time.monotonic)
- [ ] BDD .feature (флаг ON: ambient throttled at high share; direct address НЕ throttled+отвечает; delay floor) + регресс (OFF byte-identical)
- [ ] mutation ≥85% на reply_delay_inputs
- [ ] concern-4 (feed OutgoingActivityStore): УЖЕ покрыт — EpisodicOutgoingActivityStore читает episodic_log, который пишет _persist (bob_message_id). Нового write не нужно.

## Инварианты
INV-1 фокус минует ceiling (short-circuit ДО _act_reflective). INV-9 natural delay. Флаг OFF=byte-identical.

## Прогресс
ГОТОВО (dev): все 4 concern'а вшиты за флагом `presence.rhythm.enabled` (OFF=byte-identical).
- reply_rhythm.py — чистый `reply_delay_inputs` (mutation 17/17 killed, 100%).
- TurnGate: `barge_ceiling` — periphery-REPLY барж домножается на share; фокус минует (INV-1),
  OFF→нет жребия (byte-identical). +threaded через HandleMessage.
- ProactivityEngine: `share_ceiling` — throttle ДО Tier-0 gate (throttled tick = 0 LLM).
- HandleMessage: `_run_generation` (typing + DelayedTurn floor, INV-9); генерация→closure;
  OFF→прямой вызов (byte-identical). Cohesion: helper-метод, не раздут handle().
- composition: `build_rhythm_wiring` (runtime/wiring/rhythm.py) — ОДИН ShareOfVoiceGate→
  barge+share; DelayedTurn(asyncio.sleep, time.monotonic). Concern-4: store читает episodic_log
  (пишет _persist) — нового write НЕ нужно.
- BDD: presence_rhythm_wiring.feature 3 сценария (ambient throttled@high share / focus bypass /
  OFF регресс) зелёные.
- Gate: pytest 3803✓ · mypy full 0 · ruff ✓ · reindex --full + lint --strict EXIT 0 (0 циклов) ·
  coverage 99%. sync-check exit 2 (architecture.md stale — added symbols) → ВОЛНА tech-writer.

## API CHANGE
- HandleMessage.__init__: +`barge_ceiling`, +`reply_delay` (опц., None=off).
- TurnGate.__init__: +`barge_ceiling` (опц.).
- ProactivityEngine.__init__: +`share_ceiling` (опц.); `_build_proactivity_engine`: +`share_ceiling`.
- Новый флаг `presence.rhythm.enabled` + knobs `presence.rhythm.*` (share_min_multiplier/steepness,
  delay_*, window_size). Docs to check: architecture.md, domains/presence README, RFC Пласт 3.
