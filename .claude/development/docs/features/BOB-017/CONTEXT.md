<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-017 Phase A — «Боб знает свой мир»

> **Status:** Approved
> **Created:** 2026-06-25
> **Feature:** BOB-017 Phase A · родитель `bob-017`

---

## Состояние

Тир 1 закрыт; Тир 2: Goal Engine (T2.1) отгружен (дремлет), Self-Improvement (T2.2) включён.
Capability-шов (BOB-002) живой: `Capability`/`CapabilityRegistry`/`ToolLoop`, навыки `recall_memory`/
`search_memory` зарегистрированы в `_build_registry` (`app.py`). Phase A — первый shippable slice
эпика Тир-3 «Боб-кодер»; **только чтение, локально, без записи/исполнения CLI**. Фазы B (гейтед
исполнение Claude Code в изоляции) и C (стрим + self-proposed) — вне объёма.

## Ключевые решения (из PRD+RFC)

- **За существующим швом**, без нового транспорта: 3 навыка `permission="safe"` —
  `inspect_architecture` (beadloom ctx/graph/why/search), `read_code` (glob/grep+чтение), `list_work`
  (bd ready/show).
- **DDD/Clean:** `PrivacyGuard` (чистый домен, DENY-инвариант) ← порт `RepoIntrospector` ←
  `SubprocessRepoIntrospector` (инфра: `create_subprocess_exec`, фикс-allowlist read-подкоманд, без
  shell) ← фабрики навыков (приложение) ← регистрация в `app.py`.
- **🔴 Приват-инвариант (не опция):** запрещены `data/soul/**`, `data/bob.db*`, `.env*`, `config/**`;
  ALLOW только `src/`/`tests/`/`docs/`+граф-метаданные. Enforce на инфра-границе ДО чтения, не промптом.
- **Границы стадии:** навыки НЕ в автономном `goals.safe_capabilities` → только диалоговые. Никакой
  записи/исполнения произвольного CLI/сети.
- Конфиг `introspection.enabled` дефолт **true** (read-only, чат owner-only). Нет миграций БД.

## Стандарты кода (из CLAUDE.md §0.1)

- **Стек:** Python 3.12+ (asyncio), SQLite+FTS5+sqlite-vec, python-telegram-bot/aiogram, Ollama (Qwen).
- **Архитектура:** DDD + Clean — `domain/` (чистое, без I/O) ← `application/` ← `infrastructure/`;
  композиция только в `app.py`; порты инжектируются; Clock/seeded-RNG для детерминизма.
- **Качество:** TDD; `.venv/bin/pytest -q -p no:cacheprovider` (uv run **висит**); `.venv/bin/ruff
  check src/ tests/`; `.venv/bin/mypy src/ tests/` (`--strict`); покрытие ≥80%.
- **Анти-паттерны:** без `Any`/`# type: ignore` без причины; без `print()`/`breakpoint()`; без голого
  `except:`; без `import *`; без мутабельных дефолт-аргументов; subprocess через `exec` (не shell).
- **Документы:** русский. **Беады:** `--claim` перед работой, `bd close` после; чекпойнты
  `bd comments add`.

## Связи

- PRD/RFC BOB-017 Phase A; память `bob-017-dev-assistant-plan` (findings #3/#4 приватность/изоляция),
  `bob-personality-simulation-philosophy`. Образец навыка: `application/capabilities/recall_memory.py`.
