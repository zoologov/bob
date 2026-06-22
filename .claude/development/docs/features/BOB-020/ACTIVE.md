<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-020 — «Эмоциональная глубина и уязвимость» (T1.2)

> **Last updated:** 2026-06-22
> **Phase:** Development
> **Feature:** bob-36q · branch `features/BOB-020`

---

## Текущий беад

**Беад:** `bob-36q.2` — dev: увлечение (Fascination) — ГОТОВО.

## Прогресс

- [x] `.1` off-day тон (voice.tone_directive) + mood→taste модуляция (mood_taste.py) + врезка
- [x] `.2` увлечение (Fascination + FascinationStore + grounded-эволюция + проявление)
- [ ] `.3` эволюция фантомов (SOUL.with_phantoms + phantom_evolution + reflect-тик + персист)
- [ ] `.4` test · `.5` review · `.6` tech-writer

### `.2` итог (dev)
- `domain/personality/fascination.py` — `Fascination` (topic+intensity+created_at), чистый,
  иммутабельный; `aged(now)` экспоненциальный полураспад (half-life 72ч), `has_faded()` (floor 0.15), границы [0,1].
- `infrastructure/persistence/fascination_store.py` — `SqliteFascinationStore` (per-persona,
  таблица `fascination_state`); `domain/ports.py` — порт `FascinationStore`.
- `application/usecases/evolve_fascination.py` — `EvolveFascination`: редкий grounded-шаг на reflect-тике
  (Tier-0 из последней рефлексии + сильных вкусов; эвристик-фоллбэк; no-op без материала); идемпотентно
  (сдвиг только когда текущее затухло — свежее с age≈0 не сдвигается повторно); intensity из конфига.
- `application/usecases/fascination_sources.py` — `RepoFascinationGrounding` (рефлексия + сильные вкусы),
  `StoreFascinationReader` (load+age, отбрасывает затухшее).
- Проявление: флаг `mention_fascination` в `ExpressionPlan`/`ExpressionFreqs`; врезка в reply-compose
  (handle_message, редко, no-op без увлечения) + проактив-compose (engine).
- Врезка эволюции: `ReflectTick.evolve_fascination` (после логирования рефлексии).
- Конфиг: `emotion.fascination.{initial_intensity,mention_freq}` + `expression.freqs.mention_fascination`.
- Тесты: +45 (856 → 901), все зелёные. ruff чисто; mypy --strict чисто на src+tests.
  architecture.md помечен stale (новые модули) — это для tech-writer (`.6`).

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-36q.1 | dev off-day+mood→taste | — | in_progress |
| bob-36q.2 | dev увлечение | .1 | blocked |
| bob-36q.3 | dev эволюция фантомов | .1 | blocked |
| bob-36q.4 | test | .1,.2,.3 | blocked |
| bob-36q.5 | review | .4 | blocked |
| bob-36q.6 | tech-writer | .5 | blocked |

## Заметки

- Dev-беады **последовательно** на одной ветке (фоновые агенты, общий tree).
- Главный принцип: «как характер, не конфиг»; guardrails (границы/плавность/идемпотентность/seeded-RNG).
- Off-day = mood-driven, **не** реляционная обида (BOB-014). Оси taste при модуляции НЕ мутируют.
- Источник: PRD/RFC/CONTEXT.
