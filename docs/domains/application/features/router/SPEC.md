<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# router — маршрутизация тиров LLM с редакцией приватности

Маршрутизатор LLM: классификация задачи, редакция приватности перед любым вызовом
модели и fallback между тирами. Узел `router` (`part_of` слоя `bob-application`,
source `src/bob/application/router/`) — единственная точка, где ход решает, на какую
модель (Tier 0 локальная / Tier 1 API) уходит запрос, и гарантирует, что приватный
контекст не покидает процесс перед Tier-1-вызовом.

## Спецификация

### Модули

- **llm_router.py** — `LLMRouter`, классификация задачи → предпочтительный тир,
  селективная редакция приватности перед Tier 1 и fallback тиров.
  - `TaskType` — виды LLM-работы, каждый маппится роутером на предпочтительный тир.
    Приватность-чувствительные и дешёвые классификаторы остаются локальными (Tier 0):
    `EXTRACT_FACTS`, `ROOM_READ`, `STALENESS_JUDGE`, `DISCLOSURE_CONSENT`,
    `WORK_JOURNAL` (BOB-087.B1 — дистилляция ключевых фактов coding-сессии в первого-лица
    операторские эпизоды; работа над репозиторием owner'а плюс фоновый side-канал, поэтому
    держится локально) и `WORK_TALK` (BOB-087.C2 — дешёвый classifier «ход про dev-работу?»
    для register-aware recall; одно слово `work`/`chat`, поэтому локально).
  - `LLMRequest` — единица LLM-работы: промпт плюс его двухканальный сплит контекста
    (`shareable_context` уходит на любой тир, `private_context` — только Tier 0).
  - `LLMRouter.run(...)` — маршрутизировать задачу на тир, редактируя приватный контекст
    перед Tier 1, с fallback при сбое.
- **reply_tier_selector.py** — `select_reply_tier(...)`, гибридный селектор тира ответа:
  выбрать быструю или качественную модель под конкретное пользовательское сообщение.

## Инварианты

- Приватный контекст (`private_context`) **никогда** не уходит на Tier 1 — редакция
  выполняется ДО любого сетевого вызова модели.
- Роутер зависит только от порта `LLMProvider` (kernel); инфраструктуру не импортирует.
- При сбое предпочтительного тира срабатывает детерминированный fallback, а не тихий отказ.

## API

Модуль `src/bob/application/router/llm_router.py`:
- `LLMRouter.run(request)` — маршрутизация одной `LLMRequest` с редакцией и fallback.
- `LLMRequest` — промпт + `shareable_context` / `private_context`.
- `TaskType` — перечисление видов работы → тир.

Модуль `src/bob/application/router/reply_tier_selector.py`:
- `select_reply_tier(...)` — гибридный выбор быстрого/качественного тира под сообщение.

## Тестирование

Тесты: `tests/application/router/test_llm_router.py`,
`tests/application/router/test_llm_router_hardening.py`,
`tests/application/router/test_reply_tier_selector.py`.

<!-- beadloom:track=src/bob/application/router/llm_router.py -->
<!-- beadloom:track=src/bob/application/router/reply_tier_selector.py -->
