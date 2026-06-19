<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-003 — GUPPI-бот (мульти-бот gateway) + topic-scope

> **Last updated:** 2026-06-19
> **Phase:** Development
> **Epic:** bob-6ub · branch `features/BOB-003`

---

## Текущий беад

**Беад:** bob-6ub.1 — dev: конфиг двух ботов (W1).
**Done when:** `telegram`-секция под два бота (bob/guppi токены, GUPPI env-маппинг) + chat_id/topic_id/owner_id; example.yaml; тесты лоадера.

## Прогресс

- [ ] W1: bob-6ub.1 (конфиг двух ботов) — старт

## Статусы беадов

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-6ub.1 | dev: конфиг двух ботов | — | open (ready) |
| bob-6ub.2 | dev: мульти-бот gateway + topic-scope | .1 | blocked |
| bob-6ub.3 | dev: GUPPI-идентичность (reject + команды) | .2 | blocked |
| bob-6ub.4 | dev: интеграция two-bot app.py + e2e | .3 | blocked |
| bob-6ub.5 | test | .4 | blocked |
| bob-6ub.6 | review | .5 | blocked |
| bob-6ub.7 | tech-writer | .6 | blocked |

**Волны (линейно):** W1 {.1} → W2 {.2} → W3 {.3} → W4 {.4} → .5 → .6 → .7.

## Заметки

- Целевые id: chat_id=-1004372947307 · bob.topic_id=32 · owner_id=27468732.
- Два токена в env: BOB_TELEGRAM__TOKEN + GUPPI_TELEGRAM__TOKEN (нестандартный префикс → явный маппинг).
- Боты — админы группы (видят все сообщения).
- Переиспользуем Authorizer + KvAllowlistStore (BOB-002); reject «не авторизован» от GUPPI, Боб не вызывается.
