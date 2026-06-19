<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-002 — Rich/стриминг + Authz + Резилентность + Capability-шов

> **Status:** Approved
> **Created:** 2026-06-19
> **Last updated:** 2026-06-19

---

## Цель

Ближний батч-фундамент под «живого» Боба: нативные rich-сообщения и стриминг (aiogram), авторизация
доступа, надёжность 24/7-петли и стабильный **Capability-шов** (на нём поедут «Память» и «Автономность»).
*(Неизменна после утверждения.)*

## Ключевые ограничения

- Python 3.12+, asyncio, **DDD/гексагон** (`infrastructure → application → domain`), `uv`,
  `mypy --strict`, `ruff`, покрытие ≥80%, TDD, инъекция `Clock`.
- **`aiogram` ≥3.29.0** (нативный Bot API 10.1: rich/стрим/thinking) — миграция с `python-telegram-bot`.
  Gateway изолирован за портом `ReplyStreamer`/EventBus; домен/приложение не трогаются.
- LLM — OpenAI-совместимый; **tool-calling** для Capability-петли (проверить MaaS ранним вызовом;
  fallback — промпт-протокол). Где трогаем LLM — тесты на **реалистичный формат reasoning-моделей**.
- **Authz — до любой экспозиции/автономности.** Секреты только из config/env.
- **Capability-шов стабилен и forward-compatible**; полная плагин-машинерия (sandbox/дискавери/
  self-creation) — отдельным эпиком, за тем же швом.

## Стандарты кода

### Язык и окружение
- **Python 3.12+**, `uv` (venv + sync).

### Архитектура
- **DDD + Clean (гексагон).** `domain` (чисто) ← `application` (use-cases/router/runtime) ←
  `infrastructure` (адаптеры). Зависимости только внутрь; порты в `domain`; композиция только в `app.py`.

### Методологии / тесты / качество
- TDD (Red→Green→Refactor), Clean Code; **pytest** + asyncio + cov ≥80% (AAA); **ruff** + **mypy --strict**
  (на `src/` И `tests/`).

### Ограничения
- Без `Any`/`# type: ignore` без причины; без `print`/голого `except`; pathlib; **параметризованный SQL**;
  `yaml.safe_load`; без `datetime.now()` без `Clock`; без мутабельных дефолтов.

## Архитектурные решения

| Дата | Решение | Причина |
|------|---------|---------|
| 2026-06-19 | **Q1** Telegram-либа = **aiogram ≥3.29.0** (миграция с PTB) | aiogram нативно даёт Bot API 10.1 (rich/стрим/thinking); PTB ещё нет |
| 2026-06-19 | **Q2** `RichBlockThinking` ← опц. поле `thinking` ответа | монолог/мысль Боба наружу как сворачиваемый блок; рендер при наличии |
| 2026-06-19 | **Q3** Authz: owner/chats из config + рантайм-allowlist в kv (SQLite) | `/authorize` переживает рестарт |
| 2026-06-19 | **Q4** Первая capability = `recall_memory` (обёртка над recall) | обкатать tool-loop e2e; агентный `search_memory` — эпик «Память» |
| 2026-06-19 | **Q5** Tool-calling: ранняя проверка MaaS + fallback промпт-протокол | риск, что MaaS не поддержит OpenAI tools |
| 2026-06-19 | Capability-шов forward-compatible; полная плагин-система — позже | избежать преждевременной абстракции; нарастить за швом без переписывания потребителей |
| 2026-06-19 | Authz-гейт — единая точка в gateway (chat-scope + user allowlist) | нет обхода; даже при утечке токена чужие чаты мертвы |

## Связанные файлы

Открывать через `beadloom ctx <ref-id>`; пути не хардкодить. Затрагиваются `infrastructure/telegram`,
`infrastructure/llm`, `application/{router,runtime,usecases}`, `domain/ports.py`, `pyproject.toml`, `app.py`.

## Текущая фаза

- **Phase:** Planning → Development
- **Текущий беад:** назначится после создания DAG
- **Блокеры:** нет
