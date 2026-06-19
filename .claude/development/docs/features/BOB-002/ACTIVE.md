<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-002 — Rich/стриминг + Authz + Резилентность + Capability-шов

> **Last updated:** 2026-06-19
> **Phase:** Development
> **Epic:** bob-j4f · branch `features/BOB-002`

---

## Текущий беад

**Беад:** — (W1 завершён; следующий ready — bob-j4f.2 Rich + Thinking).
**Предыдущий:** bob-j4f.1 (aiogram-миграция) — DONE, закрыт.

## Прогресс

- [x] W1: bob-j4f.1 (aiogram-миграция) — DONE. Gateway переписан на aiogram 3.29 за портом
      ReplyStreamer/EventBus; стрим `send_message_draft` (батч/троттл/backoff) + commit `send_message`;
      дедуп по update_id; dep-свап pyproject (PTB удалён, aiogram добавлен); app.py — AiogramBotAdapter
      + `_build_real_bot` на aiogram. Тесты на fake-aiogram (без сети). pytest 269 / ruff / mypy --strict
      (src+tests) — зелёные. Доки architecture.md — стейл (BEAD-10 tech-writer).

## Статусы беадов

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-j4f.1 | dev: aiogram migration | — | open (ready) |
| bob-j4f.2 | dev: Rich + Thinking | .1 | blocked |
| bob-j4f.3 | dev: Authz | .2 | blocked |
| bob-j4f.4 | dev: tick resilience | — | open |
| bob-j4f.5 | dev: Capability seam | — | open |
| bob-j4f.6 | dev: recall_memory capability | .5 | blocked |
| bob-j4f.7 | dev: integration + e2e | .3, .4, .6 | blocked |
| bob-j4f.8 | test | .7 | blocked |
| bob-j4f.9 | review | .8 | blocked |
| bob-j4f.10 | tech-writer | .9 | blocked |

**Волны (с учётом venv-safety):** W1 {.1 соло} → W2 {.2, .4, .5} ∥ → W3 {.3, .6} ∥ → W4 {.7} → .8 → .9 → .10.

## Заметки

- Решения: aiogram (Q1) · thinking-поле (Q2) · authz config+kv (Q3) · recall_memory (Q4) · tool-calling+fallback (Q5).
- Только .1 трогает app.py/pyproject; .4/.5/.6 откладывают сборку на .7 (без гонок на app.py).
- Где трогаем LLM — тесты на реалистичный формат reasoning-моделей.
