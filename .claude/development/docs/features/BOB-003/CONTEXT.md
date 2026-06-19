<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-003 — GUPPI-бот (мульти-бот gateway) + topic-scope

> **Status:** Approved
> **Created:** 2026-06-19
> **Last updated:** 2026-06-19

---

## Цель

GUPPI обретает идентичность (привратник/админ в General), Боб живёт в своём топике, заложен мульти-бот
шов под Bobiverse. Один процесс, два бота. *(Неизменна после утверждения.)*

## Ключевые ограничения

- Python 3.12+, asyncio, **DDD/гексагон**, `uv`, `mypy --strict`, `ruff`, покрытие ≥80%, TDD.
- **aiogram**: один Dispatcher поллит несколько Bot за `BotRegistry`; identity в хендлере. Изоляция
  ботов опирается на резилентность BOB-002.
- Боты — **админы группы** (видят все сообщения; privacy решён операционно).
- Секреты только из env: `BOB_TELEGRAM__TOKEN` + `GUPPI_TELEGRAM__TOKEN` (нестандартный префикс →
  явный маппинг в лоадере). Тесты на фейк-ботах (без сети).
- Целевые id: `chat_id=-1004372947307`, `bob.topic_id=32`, `owner_id=27468732`.

## Стандарты кода

### Архитектура
- **DDD + Clean (гексагон).** `domain` (чисто) ← `application` ← `infrastructure`. Telegram только в
  infrastructure, за портом `ReplyStreamer`/EventBus. Композиция только в `app.py`.

### Тесты / качество
- TDD (Red→Green→Refactor); **pytest** + asyncio + cov ≥80% (AAA); **ruff** + **mypy --strict** (на `src/` И `tests/`).

### Ограничения
- Без `Any`/`# type: ignore` без причины; без `print`/голого `except`; pathlib; параметризованный SQL;
  `yaml.safe_load`; без `datetime.now()` без `Clock`; без мутабельных дефолтов.

## Архитектурные решения

| Дата | Решение | Причина |
|------|---------|---------|
| 2026-06-19 | Один процесс, **два бота** за `BotRegistry` (Боб + GUPPI) | проще (общие DB/память/heartbeat); aiogram нативно поллит N ботов; шов под реплики |
| 2026-06-19 | **Центральный роутер** по identity+scope + **кросс-бот дедуп** `(chat_id, message_id)` | оба бота-админа видят сообщение → обрабатываем один раз |
| 2026-06-19 | **Видимый reject** «не авторизован» от GUPPI; Боб не вызывается; DM незнакомца — молчим | GUPPI = привратник; без раскрытия вне группы |
| 2026-06-19 | **Topic-scope:** Боб только в `topic_id=32`, ответ в свой тред | Боб в своём топике, General служебный (под GUPPI) |
| 2026-06-19 | GUPPI переиспользует `Authorizer` + `KvAllowlistStore` (BOB-002) | не дублируем authz; владелец логики — GUPPI-идентичность |
| 2026-06-19 | GUPPI токен из `GUPPI_TELEGRAM__TOKEN` — явный маппинг | нестандартный env-префикс |

## Связанные файлы

Открывать через `beadloom ctx <ref-id>`. Затрагиваются `infrastructure/telegram`, `infrastructure/config`,
`application/authz`, `app.py`.

## Текущая фаза

- **Phase:** Planning → Development
- **Текущий беад:** назначится после создания DAG
- **Блокеры:** нет
