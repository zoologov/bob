<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-038 — T3.A⁺ «Архитектурный контекст»

> **Status:** Approved
> **Created:** 2026-06-25
> **Feature:** BOB-038 · родитель `bob-038`

---

## Состояние

T3.A отгружен (read_code/inspect_architecture/list_work + BOB-031 заземление + BOB-034 read-scope на
roadmap/dev-docs/feature-доки + BOB-035/037 схемы). Боб видит синтаксис и граф, но не помнит ПОЧЕМУ
код такой. BOB-038 (идея самого Боба, T3.A⁺) — read-only навык, связывающий код↔решения. Поверх
существующего шва (`RepoIntrospector`/`SubprocessRepoIntrospector`/`PrivacyGuard`).

## Ключевые решения (из PRD+RFC)

- Навык **`code_rationale`** (`permission="safe"`) за швом: связка код → git-история (`[BOB-XXX]`/`(#PR)`)
  → беады (`bd show`) → фича-доки (PRD/RFC, read-scope BOB-034) → beadloom-граф; компактный «почему» +
  честное «не зафиксировано».
- **git** добавляется в `_allow` **фикс-формами** (как `_BD_LIST_ARG_FORMS`): только `git log --oneline
  -- <path>` / `--grep=<BOB-key>`; путь+ключ валидируются; без произвольных флагов/подкоманд; `git
  show`/`blame` НЕ в v1.
- Порт `RepoIntrospector.code_history(path)`; домен-парсер `parse_bead_refs`/`feature_doc_dir` (чистые).
- 🔴 Приват-инвариант цел: `read_file` через `PrivacyGuard` (deny SOUL/`bob.db`/`.env`/`config`); git —
  только read-log фикс-формы (без shell/инъекций). Read-only; **не** в `goals.safe_capabilities`.

## Стандарты кода (из CLAUDE.md §0.1)

- **Стек:** Python 3.12+ (asyncio), SQLite+FTS5+vec, Telegram, Ollama (Qwen Tier-0/1).
- **Архитектура:** DDD + Clean — `domain/` (чистое, без I/O) ← `application/` ← `infrastructure/`;
  композиция в `app.py`; порты инжектируются; subprocess — `exec` без shell, фикс-allowlist.
- **Качество:** TDD; `.venv/bin/pytest -q -p no:cacheprovider` (uv run висит); `.venv/bin/ruff check
  src/ tests/`; `.venv/bin/mypy src/ tests/` (`--strict`); ≥80%.
- **Анти-паттерны:** без `Any`/`# type: ignore` без причины; без `print`/голого `except`/`import *`/
  мутабельных дефолтов; subprocess через `exec` (не shell).
- **Документы:** русский. **Беады:** `--claim` перед, `bd close` после, чекпойнты `bd comments add`.

## Связи

- PRD/RFC BOB-038; опора T3.A (`subprocess_introspector.py`/`privacy_guard.py`/`read_code.py`/
  `inspect_architecture.py`) + BOB-034 (read-scope). Память: `bob-017-dev-assistant-plan`,
  `bob-personality-simulation-philosophy`.
