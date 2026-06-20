<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-011 — Эпик «Память Боба» (семантика + агентный поиск + консолидация)

> **Status:** Approved
> **Created:** 2026-06-20

---

## Обзор

Гибридная память за портом `MemoryRecall` (drop-in, потребители не меняются): **локальные эмбеддинги
BGE-M3 через Ollama** → **sqlite-vec** (вектор-KNN в нашей же SQLite) → слияние с FTS5(BM25) через **RRF**
→ **Qwen3-Reranker** (top-K → top-N). Плюс агентная capability **`search_memory`** (Боб сам ищет через
tool-loop). Всё **локально/приватно** (контент памяти не уходит наружу). Стек подтверждён deep-research
(verified claims), решение 2026-06-20.

## Технический контекст

### Ограничения
- Python 3.12+, DDD, `uv`, `mypy --strict`, `ruff`, cov ≥80%, TDD. Инъекция `Clock`. Секреты из env.
- **Локальность:** эмбеддинги/реранк — на машине (Ollama), вектора — в локальной SQLite. Ноль внешних вызовов с контентом памяти.
- **CI без сети:** Embedder/Reranker — за портами, в тестах фейки (Ollama не в CI). Опц. интеграционный прогон вне CI.
- Реактивный чат/проактив (BOB-001..010) и authz/routing не ломать. Шов `MemoryRecall` заложен в P0.

### Стек (заблокирован)
- **Embedder:** BGE-M3 (dense **1024-dim**, мультиязычный/русский, 8192 ctx) через **Ollama** (OpenAI-совместимо).
  Порт `Embedder` провайдер-агностичен → A/B-свап на Qwen3-Embedding-4B без изменения потребителей.
- **Vector store:** **sqlite-vec** (vec0 virtual table) в существующей БД.
- **Hybrid:** FTS5(BM25) + sqlite-vec(KNN) → **RRF**.
- **Reranker:** **Qwen3-Reranker** (локально) за портом `Reranker`.

### Затрагиваемые области
`domain/ports.py` (`Embedder`, `Reranker`), `infrastructure/llm` (Ollama-embedder/reranker за OpenAI-клиентом/
scorer), `infrastructure/persistence` (sqlite-vec схема, бэкфилл, гибридный recall, on-write embed),
`application/capabilities` (`search_memory`), `app.py` (сборка), `config` (Ollama base_url/модели/dim).

## Предлагаемое решение — Фаза 1

### Эмбеддинги (порт + Ollama)
- **`Embedder`** порт: `embed(texts) -> list[vector]`. **`OllamaEmbedder`** — POST `/api/embeddings`
  (или OpenAI-совместимый `/v1/embeddings`) на локальный Ollama, модель `bge-m3`, dim 1024. Батчинг, ретраи
  (резилентность BOB-002). Конфиг: `embeddings.base_url`, `model`, `dim`.

### Vector store (sqlite-vec)
- Подключить расширение `sqlite-vec`; `vec0` virtual table `memory_vec(rowid, embedding float[1024])`,
  связанная с `semantic_memory`/`episodic_log`. **Бэкфилл:** проэмбеддить существующие факты+эпизоды
  (идемпотентно, чанк по необходимости). **On-write:** новый факт/эпизод эмбеддится при записи.

### Гибридный recall (за `MemoryRecall`)
- Кандидаты: FTS5(BM25) top-K + sqlite-vec(KNN) top-K → **RRF**-слияние (взвешенный ранг-фьюжн) →
  **Qwen3-Reranker** переоценивает top-K → **top-N** результат. Drop-in замена keyword-recall (тег source).
- Дёшево/быстро: эмбеддинг запроса — один локальный вызов; реранк — на ~20–50 кандидатах.

### Агентный `search_memory` (capability)
- Capability `search_memory(query, k)` через tool-loop: Боб сам решает поискать, реальным запросом, по
  всему архиву (гибрид+реранк), возвращает релевантное. Сверх тонкого `recall_memory` (остаётся/обёртка).

### Reranker (порт)
- **`Reranker`** порт: `rerank(query, candidates) -> ranked`. **Реализация:** Qwen3-Reranker локально —
  **способ подачи открыт (Q1):** Ollama-как-LLM-scorer (yes/no-логиты/промпт) ИЛИ маленький локальный
  rerank-сервис/llama.cpp. Порт абстрактный → свопаемо.

## Фаза 2 — Консолидация (контур; беады на старте фазы)

Всплытие очень старого релевантного · суммаризация/дайджесты длинной памяти · дедуп/слияние фактов ·
опц. память-рефлексия. Зависит от Ф1 + тюнинга.

## Рассмотренные альтернативы
- **MLX для эмбеддингов** — отвергнуто: `mlx-embedding-models` сырой (v0.0.9 2024, без BGE-M3/Qwen3). Ollama зрелее.
- **API-эмбеддинги** — отвергнуто: приватность (контент памяти наружу).
- **LanceDB** — runner-up (нативный гибрид+RRF+reranker), но отдельный стор; берём sqlite-vec ради one-DB/фита.
- **Mem0/Letta/Zep** — отвергнуто: облако-by-default (Letta шлёт эмбеддинги в OpenAI/Anthropic), лишние deps, не ложатся на DDD/per-persona.
- **Только keyword (статус-кво)** — отвергнуто: пропускает смысл.

## Риски

| Риск | Вер. | Влияние | Митигация |
|---|---|---|---|
| Ollama-сервис должен быть поднят (op-зависимость) | Med | Med | Операционная заметка; graceful-фоллбэк на keyword-FTS5 если эмбеддер недоступен |
| Qwen3-Reranker подача (нет rerank в Ollama) | Med | Med | Порт `Reranker` абстрактный; Q1 решит способ; фоллбэк — без реранка (гибрид) |
| sqlite-vec зрелость/расширение | Low | Med | Проверено (AIngram); фоллбэк keyword; контрактные тесты |
| Стоимость бэкфилла | Low | Low | Идемпотентно, батч, в фоне |
| CI без Ollama | Low | Low | Фейки за портами; интеграция вне CI |

## Открытые вопросы

| # | Вопрос | Предложение |
|---|--------|-------------|
| Q1 | Подача Qwen3-Reranker локально | Ollama-как-scorer (промпт/логиты) для v1; абстрактный порт; иначе мини-сервис |
| Q2 | Чанкинг эпизодов для эмбеддинга | По сообщению/абзацу (короткие эпизоды — целиком); тюнить |
| Q3 | Размерность/хранение | BGE-M3 dense 1024 как есть (не MRL); ~10^4–10^5 векторов — ок для sqlite-vec |
| Q4 | Когда реранкать | На `search_memory` и гибрид-recall для ответов; топ-K ~20–50 → top-N ~5–8 |
| Q5 | Фоллбэк при недоступном Ollama | Деградация на keyword-FTS5 (Боб не «теряет память», просто без семантики) |
