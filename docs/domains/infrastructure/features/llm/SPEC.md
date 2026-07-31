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
  - `build_tier_providers(...)` — построить провайдеры Tier 0 (локальный) и Tier 1 (API).
  - `build_web_search_provider(...)` — построить провайдер веб-поиска.
- **__init__.py** — фасад пакета (OpenAI-совместимый провайдер + Tier 0/1 провайдеры).

## Инварианты

- `OpenAICompatProvider` реализует контракт `LLMProvider` (kernel) структурно —
  приложение зависит от порта, а не от этого конкретного адаптера.
- Сетевой ввод-вывод изолирован в этом адаптере; домен и use-case'ы к aiohttp не касаются.
- `complete_with_tools` несёт богаче-типизированные `ToolLoopMessage` (структурный
  `tool_calls`); обычный `complete` остаётся string-only.

## API

Модуль `src/bob/infrastructure/llm/openai_compat.py`:
- `OpenAICompatProvider.complete(messages, *, stream=False)` → завершение чат-хода.
- `OpenAICompatProvider.complete_with_tools(...)` → нативный tool-calling ход.

Модуль `src/bob/infrastructure/llm/factory.py`:
- `build_tier_providers(...)` → провайдеры Tier 0 / Tier 1.
- `build_web_search_provider(...)` → провайдер веб-поиска.

## Тестирование

Тесты: `tests/infrastructure/llm/test_factory.py`,
`tests/infrastructure/llm/test_ollama_embedder_hardening.py`,
`tests/infrastructure/llm/test_ollama_reranker.py`,
`tests/infrastructure/llm/test_web_search_qwen.py`, и суждения на Tier 0
(`test_response_judge.py`, `test_reaction_judge.py`, `test_room_reader.py`).

<!-- beadloom:track=src/bob/infrastructure/llm/openai_compat.py -->
<!-- beadloom:track=src/bob/infrastructure/llm/factory.py -->
