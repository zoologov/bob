<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-003 — GUPPI-бот (мульти-бот gateway) + topic-scope

> **Last updated:** 2026-06-19
> **Phase:** Development
> **Epic:** bob-6ub · branch `features/BOB-003`

---

## Текущий беад

**Беад:** bob-6ub.4 — dev: интеграция two-bot app.py + e2e (W4). **Готов.** Следующий: bob-6ub.5 (test ≥80% + приёмка US-1..US-4).

## Прогресс

- [x] W1: bob-6ub.1 (конфиг двух ботов)
- [x] W2: bob-6ub.2 — multibot.py: BotRegistry + 2-бот поллинг + центр. роутер + кросс-бот дедуп (chat_id,message_id) + Bob topic-scope + thread-reply + изоляция. Хуки под unauthorized/GUPPI оставлены для BEAD-03. 429 тестов зелёные, ruff/mypy --strict чисто.
- [x] W3: bob-6ub.3 — GUPPI-идентичность (reject + owner-команды). 442 теста.
- [x] W4: bob-6ub.4 — app.py строит ОБА бота (env-токены telegram.bob.token/telegram.guppi.token), BotRegistry (BOB scope chat_id+bob.topic_id, GUPPI General), один MultiBotGateway поллит оба; HandleMessage стримит через multibot.reply_streamer(BOB) → ответ в тред Боба; GuppiHandler из живого Authorizer+KvAllowlistStore. e2e tests/test_e2e_two_bot.py (5): регистрация, reject+Боб-не-вызван, авторизованный→ответ-в-тред, owner authorize персистентно, General/другой-топик игнор. Мигрированы app/authz/hardening/e2e_flow/acceptance тесты на two-bot. 447 тестов; ruff чисто; mypy --strict чисто на src+tests. Doc-stale architecture.md (app.py+telegram+config) → tech-writer .7.

## Статусы беадов

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-6ub.1 | dev: конфиг двух ботов | — | closed |
| bob-6ub.2 | dev: мульти-бот gateway + topic-scope | .1 | closed |
| bob-6ub.3 | dev: GUPPI-идентичность (reject + команды) | .2 | closed |
| bob-6ub.4 | dev: интеграция two-bot app.py + e2e | .3 | closed |
| bob-6ub.5 | test | .4 | ready |
| bob-6ub.6 | review | .5 | blocked |
| bob-6ub.7 | tech-writer | .6 | blocked |

**Волны (линейно):** W1 {.1} → W2 {.2} → W3 {.3} → W4 {.4} → .5 → .6 → .7.

## Заметки

- Целевые id: chat_id=-1004372947307 · bob.topic_id=32 · owner_id=27468732.
- Два токена в env: BOB_TELEGRAM__TOKEN + GUPPI_TELEGRAM__TOKEN (нестандартный префикс → явный маппинг).
- Боты — админы группы (видят все сообщения).
- Переиспользуем Authorizer + KvAllowlistStore (BOB-002); reject «не авторизован» от GUPPI, Боб не вызывается.
