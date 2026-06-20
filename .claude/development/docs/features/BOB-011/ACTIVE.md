<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-011 — Эпик «Память Боба» (Фаза 1)

> **Last updated:** 2026-06-20
> **Phase:** Development — Фаза 1
> **Epic:** bob-6vo · branch `features/BOB-011`

---

## Текущий беад

**Беад:** W4 — bob-6vo.4 (Reranker) ∥ bob-6vo.5 (search_memory) — оба разблокированы.

## Прогресс

- [ ] Setup: `scripts/setup-ollama.sh` — установка Ollama + pull bge-m3 (+ реранкер) — в процессе
- [x] W1: bob-6vo.1 (Embedder + Ollama) — DONE.
- [x] W2: bob-6vo.2 (sqlite-vec + бэкфилл + on-write) — DONE.
- [x] W4: bob-6vo.4 (Reranker) — DONE. `Reranker` порт (domain/ports.py:
      `async rerank(query, candidates) -> list[Recalled]`), `OllamaReranker`
      адаптер (infrastructure/llm/ollama_reranker.py, Ollama-as-scorer
      per-candidate через /v1/chat/completions + retry; недоступность/ошибка/
      непарсимый score -> вход без изменений + лог), `build_reranker` factory
      (config reranker.{enabled,base_url,model,top_n}; None при absent/disabled,
      enabled=false by default), врезка в `HybridMemoryRecall` опциональным
      reranker-коллаборатором (top-K RRF pool -> rerank -> [:k]). ADDITIVE:
      None/disabled/ошибка -> гибрид без изменений (нет регрессии). +22 теста на
      фейках (no net). 678 passed / ruff / mypy --strict (src+tests). app.py
      wiring — на .6; architecture.md doc refresh — на .9.
- [x] W3: bob-6vo.3 (гибридный recall FTS5+vector+RRF) — DONE. `HybridMemoryRecall`
      (infrastructure/persistence/hybrid_recall.py) за `MemoryRecall` drop-in: эмбед запроса →
      sqlite-vec KNN (`MemoryVectorStore.knn` / `SqliteMemoryRepo.vector_knn`) + FTS5 BM25 →
      RRF-слияние (k0=60, пул=20) → дедуп → top-N с тегом source. Graceful-фоллбэк: эмбеддер
      недоступен/падает → чистый FTS5 (лог). 8 тестов на StubEmbedder. pytest 650 / ruff /
      mypy --strict зелёные. Врезка в app.py — на .6.

## Статусы беадов (Фаза 1)

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-6vo.1 | dev: Embedder + OllamaEmbedder (BGE-M3) | — | ready |
| bob-6vo.2 | dev: sqlite-vec + бэкфилл + on-write | .1 | done |
| bob-6vo.3 | dev: гибридный recall (FTS5+vector+RRF) + фоллбэк | .2 | done |
| bob-6vo.4 | dev: Reranker + Qwen3-Reranker (Q1) | .3 | done |
| bob-6vo.5 | dev: search_memory capability | .3 | ready |
| bob-6vo.6 | dev: интеграция app.py + e2e | .4,.5 | blocked |
| bob-6vo.7 | test | .6 | blocked |
| bob-6vo.8 | review (приватность) | .7 | blocked |
| bob-6vo.9 | tech-writer (+ ops-note Ollama) | .8 | blocked |

**Волны:** W1 {.1} → W2 {.2} → W3 {.3} → W4 {.4, .5} ∥ → W5 {.6} → .7 → .8 → .9.

## Заметки

- Стек заблокирован (deep-research verified): BGE-M3/Ollama + sqlite-vec + RRF + Qwen3-Reranker; локально/приватно; hand-roll.
- Установщик `scripts/setup-ollama.sh` — идемпотентный, под M4, переиспользуем для будущих Bobiverse-юзеров.
- Q1 (подача Qwen3-Reranker) — за швом, решается на .4; гибрид шиппится без него. Фоллбэк: нет Ollama → keyword-FTS5.
- Dev/CI на фейках (Ollama не в CI); live — на установленном Ollama.
