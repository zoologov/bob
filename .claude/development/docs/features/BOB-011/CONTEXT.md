<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-011 — Эпик «Память Боба»

> **Status:** Approved
> **Created:** 2026-06-20
> **Last updated:** 2026-06-20

---

## Цель

Боб помнит как книжный Боб: находит релевантное **по смыслу** (не только по словам), **сам ищет** по
всей истории, приватно (локальные эмбеддинги). Фундамент под человечность (колбэки/протекающая жизнь).
*(Неизменна после утверждения.)*

## Ключевые ограничения

- Python 3.12+, DDD, `uv`, `mypy --strict`, `ruff`, cov ≥80%, TDD. Инъекция `Clock`. Секреты из env.
- **Локальность/приватность:** эмбеддинги/реранк через **Ollama** на машине; вектора в локальной SQLite;
  **ноль внешних вызовов с контентом памяти**.
- **CI без сети:** Embedder/Reranker за портами → фейки в тестах. Реактивный чат/проактив не ломать.
- **Фоллбэк:** Ollama недоступен → деградация на keyword-FTS5 (Боб не «теряет память»).

## Стандарты кода

### Архитектура
- **DDD + Clean.** `domain` (порты `Embedder`/`Reranker`/`MemoryRecall`) ← `application`
  (`search_memory`) ← `infrastructure` (Ollama, sqlite-vec, hybrid). Композиция в `app.py`.

### Тесты / качество
- TDD; pytest + asyncio + cov ≥80%; ruff + mypy --strict (src+tests); pytest-timeout net.

### Ограничения
- Без `Any`/`# type: ignore` без причины; без `print`/голого `except`; **параметризованный SQL**; pathlib;
  без `datetime.now()`/`random` без инъекции.

## Архитектурные решения (стек — заблокирован 2026-06-20, deep-research verified)

| Решение | Причина |
|---------|---------|
| **Embedder = BGE-M3** (dense 1024) через **Ollama** (OpenAI-совм.), порт провайдер-агностичен | доказанный русский (ruMTEB Retrieval 74.79), компактный; A/B-свап на Qwen3-4B |
| **MLX для эмбеддингов — НЕ берём** | `mlx-embedding-models` сырой (v0.0.9 2024, без BGE-M3/Qwen3); Ollama зрелее |
| **Vector store = sqlite-vec** (в нашей БД) | one-DB/фит с FTS5; проверено (AIngram); приватно; LanceDB — runner-up |
| **Hybrid = FTS5(BM25)+sqlite-vec(KNN)→RRF** | смысл И слова; RRF-фьюжн |
| **Reranker = Qwen3-Reranker** за портом; подача — Q1 (Ollama-scorer), врезается отдельным беадом | буст поверх, не фундамент; Q1 не блокирует (гибрид шиппится без него) |
| **Hand-roll** (не Mem0/Letta/Zep) | фреймворки облако-by-default (приватность), лишние deps, не на DDD |
| **Фоллбэк на keyword-FTS5** при недоступном Ollama | Боб не теряет память |

## Связанные файлы

`domain/ports.py`, `infrastructure/llm` (Ollama embedder/reranker), `infrastructure/persistence`
(sqlite-vec/гибрид/бэкфилл), `application/capabilities` (`search_memory`), `app.py`, `config`.

## Текущая фаза

- **Phase:** Planning → Development (Фаза 1)
- **Блокеры:** нет (Q1 подача reranker — за швом, не блокирует)
