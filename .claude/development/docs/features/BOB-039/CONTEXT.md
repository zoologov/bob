<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-039 — T3.B «Боб запускает Claude Code» (гейтед)

> **Status:** Approved
> **Created:** 2026-06-26
> **Feature:** BOB-039 · родитель `bob-039`

---

## Состояние

T3.A/T3.A⁺ отгружены (Боб знает свой мир + историю решений). T3.B — Боб **исполняет** работу руками
локального `claude` CLI (v2.1.191, подписка) на своём репо, owner валидирует. Прецедент архитектуры —
**BOB-015 Goal Engine** (гейтед персист-процесс под owner-контролем). v1 — **user-driven** (self-
proposed из Goal Engine — T3.C, не сейчас).

## Ключевые решения (из PRD+RFC)

- `claude_code` = **гейтед сессия** `CodingSession` (state-машина PROPOSED→PLANNING→PLAN_READY→
  EXECUTING→PR_OPEN→DONE/CANCELLED/FAILED), не request→response. Owner-команды двигают гейты.
- **🔴 Изоляция:** claude в отдельном **git worktree** (`git worktree add -b bob/<slug>`) — личные
  данные gitignored → их НЕТ в worktree (проверено); cleanup в `finally`.
- **Только ветка+PR, НИКОГДА main:** use-case физически без пути в main / `gh pr merge`; мержит owner.
- **Двойной гейт:** EXECUTING только после явного `approve_plan`; мерж — вне Боба. **Owner-only** +
  kill-switch (`/code stop`). **Дефолт `coder.enabled=false`**. НЕ в `goals.safe_capabilities`.
- **Plan-mode** Claude Code (`--permission-mode plan`) — план без правок (гейт плана). stream-json →
  чистый `narrate()` → нарратив в Telegram. Локальный CLI на подписке (не API).
- Слои по образцу `goals/`: домен `coding/` (машина+narrate+имена) ← порты (`ClaudeCodeRunner`/
  `Worktree`/`CodingSessionStore`/`PullRequestOpener`) ← инфра (subprocess/git/gh/sqlite) ← use-case
  `CodingAssistant` ← GUPPI owner-команды ← `app.py`.

## Стандарты кода (из CLAUDE.md §0.1)

- **Стек:** Python 3.12+ (asyncio), SQLite, Telegram, Ollama (Qwen) + **Claude Code CLI (Tier-2)**.
- **Архитектура:** DDD + Clean — `domain/` (чистое, без I/O) ← `application/` ← `infrastructure/`;
  композиция в `app.py`; порты + Clock + seeded-RNG инжектируются; subprocess — `exec` без shell.
- **Качество:** TDD; `.venv/bin/pytest -q -p no:cacheprovider` (uv run висит); `.venv/bin/ruff check
  src/ tests/`; `.venv/bin/mypy src/ tests/` (`--strict`); ≥80%.
- **Анти-паттерны:** без `Any`/`# type: ignore` без причины; без `print`/голого `except`/`import *`/
  мутабельных дефолтов; subprocess через `exec` (не shell).
- **Документы:** русский. **Беады:** `--claim` перед, `bd close` после, чекпойнты `bd comments add`.

## Связи

- PRD/RFC BOB-039; опора BOB-015 (`domain/goals/`, governance, kill-switch, owner-команды) + T3.A
  (`PrivacyGuard`/subprocess) + `gh pr create` flow + gateway-send. Память: `bob-017-dev-assistant-plan`
  (findings изоляции #3/#4). Человек-в-петле обязателен.
