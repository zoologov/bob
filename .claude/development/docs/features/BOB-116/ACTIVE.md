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
| D9 spike qwen3:8b | bob-i83.5 | ✓ done — **A отклонён**: REFLECT 116 с холодный / 76 тёплый (порог 90), классификатор 39 / 4 (порог 15), обе модели 7,1 ГБ > 5,8 доступных → взаимное вытеснение; модель снята, VPS в исходном состоянии; Q5: autobiography=true |
| D3 монитор | bob-i83.6 | ✓ done (125 тестов; loopback 16/16 без двойного учёта; understudy_probe.py) |
| D4 owner_alert | bob-i83.7 | ✓ done (10/10, таймаут 5 с, NoopOwnerAlert) |
| D5 health_gated | bob-i83.8 | ✓ done (76/76; signature без clock; LLM-отказ по дельте consecutive_failures — D3 обязан await record_failure до re-raise) |
| D6 GUPPI /status | bob-i83.9 | ✓ done (114/114 telegram -k; render_health_status в health_status.py; часовой пояс — 3 пояса) |
| D8b деплой | bob-i83.10 | ✓ done (53 теста; deploy/check_config.py; валидация до копии; RUNBOOK §9–10; actionlint/shellcheck 0) |
| D10 сборка | bob-i83.11 | ✓ done (8510 passed; 18 тестов; две находки → D11) |
| D11 fix: старт без дублёра по-настоящему + единый часовой пояс | bob-i83.15 | in progress |
| T тесты | bob-i83.12 | blocked (D11, D8b) |
| R ревью | bob-i83.13 | blocked (T) |
| TW доки | bob-i83.14 | blocked (R) |

## Progress

- [x] task-init: оси (Explore, два seed'а), PRD c38395c, RFC 4f65884, CONTEXT+PLAN утверждены, 14 беад, DAG проверен (`bd ready` = ровно W1)
- [x] W1 + W2 (без D8b) — коммит 02071bf; гейты координатора: 8492 passed / 17 skipped, ruff/mypy чисты, lint 0 + sync 0 на чистом индексе 9.0.0; mutation D1 перемеряется в T (серийно)
- [ ] D8b + D11 (параллельно)
- [x] W3 (D10) — находки: старт без дублёра не пересобирал провайдеров, пояса UTC vs локальный → fix-беада D11 (bob-i83.15) блокирует T
- [ ] T → R → TW → PR

## Вне этой работы (зафиксировано)

- **Живой смоук** (порча ключа Tier-0 на VPS → сигнал → «восстановился») и **миграция id/секретов в `.env`
  на VPS** — при выкатке тегом **BOB-118** (`bob-sgm`), с явным «да» владельца на каждое действие; результат
  — сюда, в «Results».
- Q5 (`memory.autobiography` на VPS) — проверяется при миграции конфига.

## Results

- **Spike A (D9, 2026-10-21):** см. таблицу беад; числа — `bd comments bob-i83.5`. Решение по критериям RFC: `tier0_fallback` на VPS остаётся выключен; B (второй облачный провайдер) или замер `qwen3:4b` — отдельное решение владельца.
