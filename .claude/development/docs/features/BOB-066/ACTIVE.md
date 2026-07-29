<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-066 — между срезами

## Последний завершённый срез
**W.2-dev (bob-vol.12.2) — ЗАКРЫТ.** room-mood→тон + салиенс/бюджет consumption за флагами
`presence.room_mood.enabled` + `presence.series_budget.enabled` (OFF=byte-identical). Коммит
`0bfe2e5`. 3835 тестов зелёные, cov 99%, mypy FULL 0, ruff 0, lint --strict EXIT 0. mutation
series_salience 20/21 (95%, 1 эквивалент триаж). architecture.md doc-stale → tech-writer волна.

## Следующий фокус
**W.3-dev (bob-vol.12.3)** — staleness врезка + catch-up re-entry tick (разблокирован).

## Инварианты-напоминание
INV-1 фокус минует любой потолок/бюджет (never dropped). Флаги OFF = byte-identical.
