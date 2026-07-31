<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-07-31T12:12:20.297951+00:00 · coverage 100% (`router`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

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
