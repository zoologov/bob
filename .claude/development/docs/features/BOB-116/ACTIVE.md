<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-116 — Здоровье LLM-стека: состояние, сигнал владельцу, зонд, выкатка

> **Last updated:** 2026-10-21
> **Phase:** Development
> **Ветка:** `features/BOB-116` · **Родитель:** `bob-i83` · **Спеки:** PRD / RFC / CONTEXT / PLAN — Approved 2026-10-21

---

## Current Bead

**Волна W1** (параллельно): D1 `bob-i83.1` · D2 `bob-i83.2` · D7 `bob-i83.3` · D8a `bob-i83.4` · D9 `bob-i83.5`
**Goal:** ядро+порты, политика 401/403, автобиография, лоадер+конфиг, spike на VPS — независимые файлы.
**Done when:** пять беад закрыты с чекпоинтами; гейты на чистом индексе релизной сборкой зелёные; коммит волны.

## Beads

| Bead | Tracker | Status |
|---|---|---|
| D1 ядро+порты | bob-i83.1 | open |
| D2 classify_failure 401/403 | bob-i83.2 | open |
| D7 OUTAGE_RECOVERED | bob-i83.3 | open |
| D8a лоадер + bob.vps.yaml | bob-i83.4 | open |
| D9 spike qwen3:8b | bob-i83.5 | open |
| D3 монитор | bob-i83.6 | blocked (D1, D2) |
| D4 owner_alert | bob-i83.7 | blocked (D1) |
| D5 health_gated | bob-i83.8 | blocked (D1) |
| D6 GUPPI /status | bob-i83.9 | blocked (D1) |
| D8b деплой | bob-i83.10 | blocked (D8a, D9) |
| D10 сборка | bob-i83.11 | blocked (D3, D4, D5, D6, D7, D8a) |
| T тесты | bob-i83.12 | blocked (D10, D8b) |
| R ревью | bob-i83.13 | blocked (T) |
| TW доки | bob-i83.14 | blocked (R) |

## Progress

- [x] task-init: оси (Explore, два seed'а), PRD c38395c, RFC 4f65884, CONTEXT+PLAN утверждены, 14 беад, DAG проверен (`bd ready` = ровно W1)
- [ ] W1
- [ ] W2 (D3, D4, D5, D6, D8b)
- [ ] W3 (D10)
- [ ] T → R → TW → PR

## Вне этой работы (зафиксировано)

- **Живой смоук** (порча ключа Tier-0 на VPS → сигнал → «восстановился») и **миграция id/секретов в `.env`
  на VPS** — при выкатке тегом **BOB-118** (`bob-sgm`), с явным «да» владельца на каждое действие; результат
  — сюда, в «Results».
- Q5 (`memory.autobiography` на VPS) — проверяется при миграции конфига.

## Results

_(заполняется по волнам)_
