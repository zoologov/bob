<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-011 — Эпик «Память Боба» (Фаза 1)

> **Last updated:** 2026-06-20
> **Phase:** Development — Фаза 1
> **Epic:** bob-6vo · branch `features/BOB-011`

---

## Текущий беад

**Беад:** bob-6vo.1 — dev: Embedder + OllamaEmbedder (W1) — стартует ПОСЛЕ установки Ollama.

## Прогресс

- [ ] Setup: `scripts/setup-ollama.sh` — установка Ollama + pull bge-m3 (+ реранкер) — в процессе
- [ ] W1: bob-6vo.1 (Embedder + Ollama) — ждёт установку

## Статусы беадов (Фаза 1)

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-6vo.1 | dev: Embedder + OllamaEmbedder (BGE-M3) | — | ready |
| bob-6vo.2 | dev: sqlite-vec + бэкфилл + on-write | .1 | blocked |
| bob-6vo.3 | dev: гибридный recall (FTS5+vector+RRF) + фоллбэк | .2 | blocked |
| bob-6vo.4 | dev: Reranker + Qwen3-Reranker (Q1) | .3 | blocked |
| bob-6vo.5 | dev: search_memory capability | .3 | blocked |
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
