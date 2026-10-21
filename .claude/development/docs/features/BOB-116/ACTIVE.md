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
| D1 ядро+порты | bob-i83.1 | ✓ done (45/45, 144 мутанта 100 %; API: record_* async, HealthView.failing_since datetime, failed_probes) |
| D2 classify_failure 401/403 | bob-i83.2 | ✓ done (389/389 acceptance, router 242/242, 41 мутант 100 %; S25/S26) |
| D7 OUTAGE_RECOVERED | bob-i83.3 | ✓ done (145/145; SelfAction.outage: OutageSpan — не detail; visibility решает вызывающий) |
| D8a лоадер + bob.vps.yaml | bob-i83.4 | ✓ done (72/72 config; env по типу дефолта, таймауты float, owner_name в .env; гард чистоты) |
| D9 spike qwen3:8b | bob-i83.5 | in progress (pull на VPS, Q5: autobiography=true на VPS) |
| D3 монитор | bob-i83.6 | in progress |
| D4 owner_alert | bob-i83.7 | ✓ done (10/10, таймаут 5 с, NoopOwnerAlert) |
| D5 health_gated | bob-i83.8 | ✓ done (76/76; signature без clock; LLM-отказ по дельте consecutive_failures — D3 обязан await record_failure до re-raise) |
| D6 GUPPI /status | bob-i83.9 | ✓ done (114/114 telegram -k; render_health_status в health_status.py; часовой пояс — 3 пояса) |
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
