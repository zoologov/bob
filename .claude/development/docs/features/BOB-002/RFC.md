<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-002 — Rich/стриминг + Authz + Резилентность + Capability-шов

> **Status:** Approved
> **Created:** 2026-06-19

---

## Обзор

Четыре независимых трека поверх P0-архитектуры (DDD/гексагон), все за существующими портами:
(1) Telegram-сообщения — нативный стриминг `sendMessageDraft` + Rich Messages через **сырой Bot API**
(PTB ещё без 10.1) + конвертер `markdown→RichMessage` + `RichBlockThinking`; (2) **Authz** — гейт в
gateway по owner/allowlist/chat-scope; (3) **резилентность** heartbeat-тиков (retry/backoff);
(4) **Capability-шов** — контракт + реестр + tool-use петля + манифест (Боб знает, что умеет; GUPPI =
исполнитель).

## Мотивация

См. PRD. Технически: довести транспорт до уровня современного ИИ-UX, закрыть доступ, сделать петлю
надёжной и заложить **стабильный шов навыков**, на котором поедут «Память» и «Автономность» — **не
переписывая потребителей** при наращивании.

## Технический контекст

### Ограничения
- Python 3.12+, asyncio, DDD (`infrastructure → application → domain`), `uv`, `mypy --strict`, `ruff`,
  покрытие ≥80%, TDD. Инъекция `Clock`. Секреты только из config/env.
- **`aiogram` ≥3.29.0 поддерживает Bot API 10.1 нативно** (Rich Messages + `sendRichMessage`/Draft +
  `RichBlockThinking` + `sendMessageDraft`). Мигрируем gateway с `python-telegram-bot` на aiogram.
- LLM — OpenAI-совместимый; tool-calling нужен для Capability-петли (qwen3.7-plus умеет; проверить MaaS).
- Где трогаем LLM — тесты на **реалистичный формат reasoning-моделей** (урок BOB-001).

### Затрагиваемые области
`infrastructure/telegram/` (gateway **переписан на aiogram** + rich-builder), `pyproject.toml`
(dep `python-telegram-bot` → `aiogram>=3.29`), `application/router` + `infrastructure/llm/openai_compat`
(tool-calling), `application/runtime/heartbeat` (retry), `application/usecases/handle_message`
(capability-петля, thinking), `domain/ports.py` (новые порты), `infrastructure/config` +
`infrastructure/persistence` (authz-стор), `app.py` (сборка).

## Предлагаемое решение

### Трек 1 — Telegram: миграция на aiogram + нативный rich/стрим/thinking

- **Миграция gateway `python-telegram-bot` → `aiogram` (≥3.29.0).** Переписываем `infrastructure/telegram/*`
  под aiogram (Dispatcher/Router, long-polling, дедуп) **за тем же портом `ReplyStreamer` + EventBus** —
  домен/приложение не трогаются. Зависимость в `pyproject` меняем.
- **Нативные методы aiogram (Bot API 10.1):** стрим — `sendMessageDraft` / `sendRichMessageDraft`;
  форматирование — `sendRichMessage` с **типизированными** `RichMessage`/`RichBlock`/`RichText`.
  **Сырой API и `RawTelegramClient` не нужны.**
- **`MarkdownToRichMessage`** (чистая трансформация, `domain`/util): markdown ответа модели → дерево
  aiogram-типов `RichMessage` (`RichBlock`: paragraph/section-heading/list/table/blockquote/
  preformatted(код)/divider; `RichText`: bold/italic/code/math/spoiler/…). Детерминированно, тестируемо.
- **`RichBlockThinking` (Must Have):** ответ Боба несёт опциональное поле `thinking` (краткая мысль/
  выдержка внутреннего монолога); gateway рендерит его как **сворачиваемый `RichBlockThinking`** +
  основной ответ обычными блоками. Источник `thinking` — лёгкая Tier 0 мысль или выдержка монолога.
- **Стриминг rich** — через `sendRichMessageDraft` (НЕ `editMessageText`+rich — известный баг, что
  edit-стрим ломает rich). Замена текущего `editMessageText`-хака.
- **Fallback:** любая ошибка rich → деградация на обычный `send_message` (никогда не отдаём ошибку
  пользователю). Сплит по лимиту длины при необходимости.
- Гейтвей остаётся адаптером; Higher-Mind-логики в нём нет.

### Трек 2 — Authz (owner + allowlist + chat-scope)

- **`Authorizer`** (application/domain, чистая политика): `owner_id`, `allowed_chat_ids`, динамический
  `allowed_user_ids`. `is_authorized(user_id, chat_id) -> bool`.
- **Гейт в gateway:** на каждом апдейте — если `chat.id` не в `allowed_chat_ids` ИЛИ `from_user.id` не
  авторизован → **молча игнор** (не публикуем `MessageReceived`). Даже при утечке токена в чужих чатах
  Боб мёртв (chat-scope).
- **Конфиг:** `telegram.owner_id`, `telegram.allowed_chat_ids`. Рантайм-allowlist персистится в
  **kv/таблице** (SQLite), чтобы `/authorize` переживал рестарт.
- **Owner-команда `/authorize <user_id>`** (только owner) добавляет в allowlist. (`/deauthorize`,
  `/whoami` — опц.)

### Трек 3 — Резилентность тиков

- **`retry_with_backoff`** (application util, инъекция `sleep`/`Clock` для детерминизма): ограниченные
  ретраи с экспоненциальным backoff на **транзиентных** ошибках (сетевые `RemoteProtocolError`/timeout,
  5xx). Перманентные — пробрасываем/логируем.
- Каждый **тик изолирован**: сбой одного тика не валит петлю и не глушит остальные (как сейчас
  «continuing», но с backoff + классификацией транзиент/перманент). Применить к heartbeat-тикам и,
  опц., к LLM-вызовам.

### Трек 4 — Capability-шов (стабильный, forward-compatible)

- **Контракт `Capability`** (`domain/ports.py`): `name`, `description`, `input_schema` (JSON Schema),
  `permission` (`safe` | `confirm` — задел под approval), `async execute(args) -> result`.
- **`CapabilityRegistry`** (application): `register()`, `manifest()` (список tool-определений),
  `dispatch(name, args)` (= **GUPPI исполняет**).
- **Tool-use петля** (в `HandleMessage`/router + `OpenAICompatProvider`): передаём `manifest()` как
  `tools` в LLM-запрос; если модель вернула `tool_calls` → реестр диспатчит → результат как
  `tool`-сообщение → повтор, пока не финальный ответ. Провайдер учится читать/отдавать `tools`/
  `tool_calls` (OpenAI-совместимо).
- **Манифест в контексте:** в системный промпт/контекст Боба кладём перечень возможностей (Боб **знает,
  что умеет**; ссылается на GUPPI в персоне).
- **Одна реальная capability для обкатки петли e2e:** `recall_memory(query)` — тонкая обёртка над
  существующим `MemoryRecall` (архивный поиск). Полноценный агентный `search_memory` + вектора — эпик
  «Память». Шов forward-compatible: новый навык = регистрация объекта; потребители не меняются.

## Рассмотренные альтернативы

- **MarkdownV2/HTML parse_mode вместо Rich Messages** — отвергнуто: хрупкое экранирование, нет
  document-grade + thinking; Rich Messages — нативное под ИИ (PRD-обсуждение).
- **`editMessageText`+rich для стрима** — отвергнуто: известный баг (edit-стрим ломает rich). Используем
  `sendRichMessageDraft`.
- **Остаться на PTB + сырой API для rich** — отвергнуто: **`aiogram>=3.29.0` уже даёт Bot API 10.1
  нативно** (rich/стрим/thinking) → переезжаем на aiogram, без сырого API. (PTB 10.1 ещё не вышел.)
- **Полная плагин-система сразу** — отвергнуто (обсуждение 2026-06-19): преждевременно при нуле навыков;
  фиксируем шов, машинерию — позже.
- **Authz через config-only** — отвергнуто для `/authorize`: рантайм-allowlist нужен персистентный (kv).

## Риски

| Риск | Вероятность | Влияние | Митигация |
|---|---|---|---|
| Миграция gateway PTB→aiogram (идиоматизм, паритет поведения) | Med | Med | Адаптер изолирован за портом `ReplyStreamer`; паритетные тесты дедуп/стрим; fallback на plain |
| MaaS-эндпоинт не поддерживает OpenAI tool-calling | Low | High | Проверить ранним вызовом; иначе — промпт-протокол tool-use как fallback |
| `RichBlockThinking`/rich-стрим UX-нюансы | Med | Low | Fallback на plain; за фичефлагом |
| Backoff маскирует реальные перманентные сбои | Low | Med | Классификация транзиент/перманент; лимит ретраев + лог |
| Authz-обход (забыли проверить ветку) | Low | High | Единая точка-гейт в gateway + тест на отказ чужим |

## Открытые вопросы

| # | Вопрос | Решение |
|---|--------|---------|
| Q1 | Telegram-либа | **Decided:** миграция на **aiogram ≥3.29.0** (нативный Bot API 10.1: rich/стрим/thinking), без сырого API |
| Q2 | Источник текста `RichBlockThinking` | **Decided:** опц. поле `thinking` (лёгкая Tier 0 мысль / выдержка монолога), рендерим при наличии |
| Q3 | Authz `/authorize` — персист | **Decided:** owner/chats из config, рантайм-allowlist в kv (SQLite) |
| Q4 | Первая capability | **Decided:** `recall_memory` (обёртка над recall) для обкатки петли; `search_memory` — эпик «Память» |
| Q5 | Tool-calling в провайдере | Проверить MaaS ранним вызовом; fallback — промпт-протокол |
