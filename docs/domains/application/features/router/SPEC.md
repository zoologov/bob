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
- **voice_integrity.py** (BOB-087.E-M1) — чистое ядро «кто вправе ответить за Боба, когда
  обслуживавший ход тир лёг». Направление фолбэка следует **виду работы, а не тиру**:
  - `OutageVoice` — вердикт: `LOCAL_UNDERSTUDY` (служебный ход — классификатор, гейт,
    монолог — деградирует на локального дублёра, как задумывал Срез E), `CLOUD_TIER1`
    (ход ГОЛОСОМ БОБА эскалируется ВВЕРХ, на качественный тир, — никогда вниз),
    `NOBODY` (говорить за Боба некому: отвал сообщается честно).
  - `who_may_answer_for_bob(...)` — чистая функция от булевых фактов хода; без I/O,
    часов и состояния. Взята под mutation отдельным файлом в `mutmut.source_paths`.
  Ядро живёт в пакете роутера (именно роутер знает тип задачи); в доменный вертикал его
  вынести нельзя — каждый домен уже импортирует роутер, и обратный импорт замкнул бы цикл.

## Инварианты

- Приватный контекст (`private_context`) **никогда** не уходит на Tier 1 — редакция
  выполняется ДО любого сетевого вызова модели.
- Роутер зависит только от порта `LLMProvider` (kernel); инфраструктуру не импортирует.
- При сбое предпочтительного тира срабатывает детерминированный fallback, а не тихий отказ.
- Голос Боба не подменяется аварийным дублёром **никогда** (BOB-087.E-M1): ход
  `REPLY_TO_USER` идёт мимо локального дублёра в обе двери (и прямой Tier-0-вызов, и
  fallback Tier 1 → Tier 0); при отвале он эскалируется вверх ровно одним прыжком, а если
  и там пусто — наружу уходит честный отвал, а не чужой голос.
- Эскалация вверх несёт ТОТ ЖЕ уже отредактированный payload: аварийный путь не проносит
  в облако ничего, чего не пронёс бы штатный Tier-1-вызов (payload строится один раз).

## API

Модуль `src/bob/application/router/llm_router.py`:
- `LLMRouter.run(request)` — маршрутизация одной `LLMRequest` с редакцией и fallback.
- `LLMRequest` — промпт + `shareable_context` / `private_context`.
- `TaskType` — перечисление видов работы → тир.

Модуль `src/bob/application/router/reply_tier_selector.py`:
- `select_reply_tier(...)` — гибридный выбор быстрого/качественного тира под сообщение.

Модуль `src/bob/application/router/voice_integrity.py`:
- `who_may_answer_for_bob(...)` — вердикт `OutageVoice` по фактам хода.
- `OutageVoice` — `LOCAL_UNDERSTUDY` / `CLOUD_TIER1` / `NOBODY`.

## Тестирование

Тесты: `tests/application/router/test_llm_router.py`,
`tests/application/router/test_llm_router_hardening.py`,
`tests/application/router/test_reply_tier_selector.py`,
`tests/application/router/test_voice_integrity.py` (чистое ядро + полная таблица
истинности), `tests/application/router/test_llm_router_voice_integrity.py`
(роутер × реальный композит-провайдер, включая инвариант приватности по всем `TaskType`).
BDD-сценарии целостности голоса и приватности аварийного пути — в
`tests/acceptance/features/tier0_fallback.feature` (S15–S21).

<!-- beadloom:track=src/bob/application/router/llm_router.py -->
<!-- beadloom:track=src/bob/application/router/reply_tier_selector.py -->
<!-- beadloom:track=src/bob/application/router/voice_integrity.py -->
