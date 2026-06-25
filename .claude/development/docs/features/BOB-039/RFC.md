<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-039 — T3.B «Боб запускает Claude Code» (гейтед)

> **Status:** Approved
> **Created:** 2026-06-26
> **Feature:** BOB-039 · реализует PRD BOB-039

---

## Контекст и опора

Прецедент — **BOB-015 Goal Engine**: гейтед персист-процесс под owner-контролем (`domain/goals/`
state-машина + `GoalStore` + governance + kill-switch + owner-команды через GUPPI). `claude_code`-
сессия строится **тем же паттерном**. Также: `gh pr create` (PR-flow), gateway-`send_message`
(нарратив), authz owner-only, T3.A `PrivacyGuard`/subprocess-без-shell. Claude Code (`claude` v2.1.191)
имеет **plan-mode** (`--permission-mode plan`) — даёт план без правок → это гейт плана.

## Ключевая идея

`claude_code` — **НЕ обычный навык request→response**, а **гейтед сессия с персист-состоянием**:
`PROPOSED → PLANNING → PLAN_READY →(апрув owner)→ EXECUTING → PR_OPEN → DONE | CANCELLED | FAILED`.
Owner-команды двигают гейты; раннер исполняет `claude` в **изолированном worktree** и **наррирует»**.

## Архитектура (DDD/Clean, по образцу goals/)

**Домен (`domain/coding/`, чистое):**
- `CodingSession` (frozen+slots) + `CodingSessionState` StrEnum-машина (переходы выше; в EXECUTING
  только после явного PLAN-апрува на уровне use-case). Чистые предикаты (можно ли стартовать/апрувить/
  стопать).
- `narrate(event: Mapping) -> str | None` — **чистый мэппер** stream-json события Claude Code
  (`assistant`/`tool_use`/`tool_result`/`result`) → короткая русская нарратив-строка («правлю X»,
  «гоняю тесты», «готово»), `None` для шумных. Тестируемо без CLI.
- `worktree_branch(task) -> str` / `worktree_dir(...)` — чистые имена (ветка `bob/<slug>`).

**Порты (`domain/ports.py`):**
- `ClaudeCodeRunner.run(workdir, prompt, *, mode) -> AsyncIterator[event]` — запуск `claude` (plan|
  execute), стрим событий.
- `Worktree.create(branch) -> path` / `Worktree.remove(path)` — изоляция.
- `CodingSessionStore` (persist сессии) · `PullRequestOpener.open(branch, title, body) -> url`.

**Инфраструктура:**
- `SubprocessClaudeRunner` — `asyncio.create_subprocess_exec(claude, "-p", prompt,
  "--output-format","stream-json", "--permission-mode", mode, cwd=worktree)` (без shell), читает
  **NDJSON построчно**, парсит события, таймаут/лимит. `mode`: `plan` (план без правок) / `acceptEdits`
  (исполнение в изолированном worktree — гейт уже на уровне PR/мержа).
- `GitWorktree` — `git worktree add <tmp> -b bob/<slug>` (трекнутые файлы only → личных данных нет,
  проверено) + `git worktree remove` в `finally`. `_allow`-стиль фикс-формы git (как BOB-038).
- `GhPullRequestOpener` — `gh pr create --base main --head bob/<slug> …`; **НИКОГДА** `gh pr merge` и
  НИКОГДА push в main (use-case физически не вызывает мерж).
- `SqliteCodingSessionStore` (таблица coding_session).

**Приложение (`application/usecases/coding_assistant.py`):**
- `CodingAssistant` оркестрирует: **start** (authz owner-only → создать worktree+ветку → `run(plan)` →
  собрать план → состояние PLAN_READY → показать owner, ждать); **approve_plan** (→ `run(acceptEdits)` →
  наррировать события через gateway → коммит в ветку → `PullRequestOpener.open` → PR_OPEN, показать
  diff/PR owner, ждать его мержа); **stop** (kill-switch → терминировать subprocess → cleanup worktree →
  CANCELLED). Governance/owner-only/kill-switch — реюз. Боб **никогда** не мержит/не пушит main.
- Owner-команды (GUPPI): `/code <task>` (start), `/code approve` (гейт плана), `/code stop` (kill),
  `/code status`. Только owner (authz); гость — отказ. Естественный язык «стоп» → тот же флаг (как в
  BOB-015).

**Telegram/GUPPI:** парс owner-команд + маршрут в `CodingAssistant`; нарратив — `gateway.send_message`
в чат owner.

**Композиция (`app.py`):** провязать порты/раннер/стор; конфиг `coder.{enabled, claude_bin, gh_bin,
worktree_root, timeout, permission_mode}`. **Дефолт `enabled=false`** (консервативно — owner включает,
как goals/self_improvement). Навык/use-case **НЕ** в `goals.safe_capabilities`.

## 🔴 Безопасность и приватность (в коде, не на словах)

- **Изоляция:** worktree = `git worktree add` (трекнутые файлы only) → `data/soul/`, `bob.db*`, `.env*`,
  `config/*` **отсутствуют** (gitignored, проверено) → Claude Code их не видит. Cleanup в `finally`.
- **Только ветка+PR, никогда main:** use-case не имеет пути в main; нет `git push origin main`, нет
  `gh pr merge`. PR открывается, **мержит owner** руками.
- **Двойной гейт:** EXECUTING только после `approve_plan` (явная owner-команда); мерж — вне Боба.
  Между гейтами сессия ждёт (персист-состояние), не действует.
- **Owner-only + kill-switch:** старт/апрув/стоп — только owner (authz); стоп терминирует прогон; не в
  автономном safe-allowlist (в v1 Боб сам не запускает).
- **Облако:** `claude` шлёт код worktree в Anthropic (суть Claude Code) — но **никаких личных данных**
  (их нет в worktree). Локальный CLI на подписке, не платный API.

## Тестирование (детерминизм через фейки)

- Домен: state-машина (легальные/нелегальные переходы; EXECUTING только после апрува); `narrate`
  (события→строки, шум→None); имена веток.
- Use-case с фейками (`ClaudeCodeRunner` отдаёт канонные события, `Worktree`/`Store`/`PROpener`/gateway
  фейки): полный гейтед-флоу; **без апрува плана нет EXECUTING**; **никогда не мерж/не push main**;
  owner-only (гость→отказ); stop терминирует+cleanup; ошибка/таймаут→FAILED честно; нарратив идёт в чат.
- Инфра: git worktree фикс-формы; claude argv (stream-json/permission-mode); NDJSON-парс; gh pr create
  (без merge). Реальный `claude` НЕ дёргаем в юнит-тестах (фейк-runner); опц. 1 smoke под флагом.
- ≥80%; `.venv/bin/*`; `beadloom ci` зелёный.

## Риски и границы

- **Главный риск — приватность/безопасность:** закрыт worktree-изоляцией (личных данных нет) + branch+
  PR-only + двойной гейт + owner-only + kill-switch. Review — отдельный security-проход.
- Claude Code может «наошибать» в worktree — не страшно: всё в ветке, под PR-ревью owner, main цел.
- Зависание/долгий прогон — таймаут + стоп + честный отчёт.
- **Вне v1:** self-proposed (T3.C, нужен Goal Engine), авто-мерж, live-многоволновость.

## Альтернативы (отвергнуто)

- **Отдельный clone вместо worktree** — тяжелее; worktree даёт ту же изоляцию личных данных дешевле.
- **Один гейт (только мерж)** — PRD требует двойной (план до исполнения); plan-mode это даёт дёшево.
- **Claude через API** — против «локальный CLI на подписке»; и API-ключ — лишний секрет.

## Этапы (детализация — в PLAN)

1. **dev** — домен `coding/` (CodingSession-машина + `narrate` + имена) + порты + `SqliteCodingSessionStore`.
2. **dev** — инфра: `GitWorktree` + `SubprocessClaudeRunner` (stream-json/NDJSON) + `GhPullRequestOpener`.
3. **dev** — `CodingAssistant` use-case (гейтед оркестрация + owner-команды + нарратив) + GUPPI-провязка + конфиг (`enabled=false`).
4. **test** — US-1..6 + двойной гейт + never-main/never-merge + owner-only + kill-switch + приватность.
5. **review** — security-проход (изоляция/гейты/never-main/owner-only/kill-switch) + DDD/детерминизм.
6. **tech-writer** — `architecture.md` (рус): claude_code-сессия, worktree-изоляция, гейты, нарратив. Gate.
