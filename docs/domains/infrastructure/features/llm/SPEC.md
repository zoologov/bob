<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# llm — адаптер LLM (OpenAI-совместимый провайдер)

Адаптер инфраструктуры для LLM: OpenAI-совместимый провайдер завершений Tier 0/1 и
tool-calling поверх aiohttp (backend — Ollama/Qwen). Узел `llm` (`part_of` слоя
`bob-infrastructure`, source `src/bob/infrastructure/llm/`) реализует порт `LLMProvider`
из kernel; вся редакция приватности и маршрутизация тиров живут выше, в узле `router`.

## Спецификация

### Модули

- **openai_compat.py** — `OpenAICompatProvider`, OpenAI-совместимый провайдер
  chat-completions поверх aiohttp: `complete(...)` (обычное завершение, опционально
  стриминг токенов) и `complete_with_tools(...)` (нативный tool-calling ход для tool-loop'а).
- **factory.py** — сборка провайдеров из конфигурации:
  - `build_tier_providers(...)` — построить провайдеры Tier 0 (локальный) и Tier 1 (API);
    при `llm.tier0_fallback` = `ollama` Tier 0 отдаётся завёрнутым в `FallbackLLMProvider`
    (пусто — по умолчанию — ровно тот же провайдер, что и раньше).
  - `build_web_search_provider(...)` — построить провайдер веб-поиска.
- **fallback_policy.py** (BOB-087.E1) — чистое ядро вердикта `should_fall_back(error)`:
  считать ли сбой поводом уйти на локальную модель. Транспорт/доступность (таймаут,
  обрыв соединения, 5xx, 408, 429) — да; контракт (прочие 4xx, битая форма ответа,
  `TypeError`, отмена) — нет, иначе фолбэк маскировал бы наши собственные баги.
- **fallback_provider.py** (BOB-087.E1) — `FallbackLLMProvider`: композит
  primary + локальный аварийный fallback, реализующий тот же порт `LLMProvider`.
- **__init__.py** — фасад пакета (OpenAI-совместимый провайдер + Tier 0/1 провайдеры).

## Инварианты

- `OpenAICompatProvider` реализует контракт `LLMProvider` (kernel) структурно —
  приложение зависит от порта, а не от этого конкретного адаптера.
- Сетевой ввод-вывод изолирован в этом адаптере; домен и use-case'ы к aiohttp не касаются.
- `complete_with_tools` несёт богаче-типизированные `ToolLoopMessage` (структурный
  `tool_calls`); обычный `complete` остаётся string-only.
- Аварийный Tier-0-фолбэк никогда не каскадит: одна попытка primary → одна попытка
  локальной модели; упали обе — наружу уходит исходная ошибка primary. Каждое
  переключение логируется `WARNING` (тихая деградация недопустима).
- `LLMRouter` о фолбэке не знает: политика живёт целиком в композите, поэтому
  маршрутизация тиров остаётся неизменной.

## API

Модуль `src/bob/infrastructure/llm/openai_compat.py`:
- `OpenAICompatProvider.complete(messages, *, stream=False)` → завершение чат-хода.
- `OpenAICompatProvider.complete_with_tools(...)` → нативный tool-calling ход.

Модуль `src/bob/infrastructure/llm/factory.py`:
- `build_tier_providers(...)` → провайдеры Tier 0 / Tier 1.
- `build_web_search_provider(...)` → провайдер веб-поиска.

Модуль `src/bob/infrastructure/llm/fallback_policy.py`:
- `should_fall_back(error)` → вердикт «это транспортный сбой, уходим на локальную модель».

Модуль `src/bob/infrastructure/llm/fallback_provider.py`:
- `FallbackLLMProvider(primary=…, fallback=…).complete(messages, *, stream=False)` →
  завершение на primary, при транспортном сбое — одна попытка на локальной модели.

Конфиг (`llm`): `tier0_fallback` (пусто = OFF; поддерживается `ollama`),
`tier0_fallback_base_url` (`http://localhost:11434/v1`), `tier0_fallback_model`
(`qwen2.5:0.5b`).

## Тестирование

Тесты: `tests/infrastructure/llm/test_factory.py`,
`tests/infrastructure/llm/test_fallback_policy.py` (чистое ядро под mutation),
`tests/infrastructure/llm/test_fallback_provider.py`,
`tests/infrastructure/llm/test_ollama_embedder_hardening.py`,
`tests/infrastructure/llm/test_ollama_reranker.py`,
`tests/infrastructure/llm/test_web_search_qwen.py`, и суждения на Tier 0
(`test_response_judge.py`, `test_reaction_judge.py`, `test_room_reader.py`).

<!-- beadloom:track=src/bob/infrastructure/llm/openai_compat.py -->
<!-- beadloom:track=src/bob/infrastructure/llm/factory.py -->
<!-- beadloom:track=src/bob/infrastructure/llm/fallback_policy.py -->
<!-- beadloom:track=src/bob/infrastructure/llm/fallback_provider.py -->
