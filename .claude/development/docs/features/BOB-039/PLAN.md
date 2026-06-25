<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-039 — T3.B «Боб запускает Claude Code» (гейтед)

> **Status:** Approved
> **Created:** 2026-06-26
> **Feature:** BOB-039 · родитель `bob-039`

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (домен + порты + стор) | `domain/coding/`: `CodingSession` (frozen+slots) + `CodingSessionState` StrEnum-машина (PROPOSED→PLANNING→PLAN_READY→EXECUTING→PR_OPEN→DONE/CANCELLED/FAILED; EXECUTING только из PLAN_READY) + чистые предикаты; чистый `narrate(event)->str|None` (stream-json событие→рус-строка/шум→None); `worktree_branch(task)`/имена. Порты `ClaudeCodeRunner`/`Worktree`/`CodingSessionStore`/`PullRequestOpener` в `domain/ports.py`. `SqliteCodingSessionStore` (+схема). Юнит-тесты машины+narrate. | — |
| `.2` | **dev** (инфра: worktree/claude/gh) | `infrastructure/coding/`: `GitWorktree` (`git worktree add -b bob/<slug>` фикс-формы + `remove` в finally; трекнутые файлы only → личных данных нет); `SubprocessClaudeRunner` (`create_subprocess_exec` claude `-p ... --output-format stream-json --permission-mode <plan|acceptEdits>` cwd=worktree, без shell, NDJSON построчно→события, таймаут/лимит); `GhPullRequestOpener` (`gh pr create --base main --head bob/<slug>`; БЕЗ `gh pr merge`/push main). Юнит-тесты (argv/формы/NDJSON-парс/cleanup; фейк-runner, без реального claude). | `.1` |
| `.3` | **dev** (use-case + owner-команды + нарратив) | `application/usecases/coding_assistant.py`: `CodingAssistant` — start(authz owner→worktree→run(plan)→PLAN_READY→показать), approve_plan(→run(acceptEdits)→narrate в gateway→commit ветка→PR_OPEN→показать diff/PR, ждать мержа owner), stop(kill→terminate→cleanup→CANCELLED). Реюз authz/governance/kill-switch. **Никогда** merge/push main. GUPPI owner-команды `/code <task>`/`approve`/`stop`/`status` (гость→отказ; естественный «стоп»→флаг). Провязка в `app.py`; конфиг `coder.{enabled=false, claude_bin, gh_bin, worktree_root, timeout, permission_mode}`. НЕ в `goals.safe_capabilities`. | `.1,.2` |
| `.4` | **test** | ≥80% + US-1..6 + **двойной гейт** (без апрува плана нет EXECUTING) + **never-main/never-merge** (нет пути в main/`gh pr merge`) + owner-only (гость→отказ) + kill-switch (stop terminate+cleanup) + приватность (worktree без личных данных) + ошибка/таймаут→FAILED + регрессии (T3.A/диалог/authz/goals). Фейк-runner (без реального claude). `.venv/bin/pytest`. | `.1,.2,.3` |
| `.5` | **review** | **SECURITY-проход:** изоляция worktree (нет личных данных), never-main/never-merge железно, двойной гейт непробиваем (EXECUTING только из PLAN_READY по owner-команде), owner-only, kill-switch, `coder.enabled=false` дефолт, не в safe-allowlist; claude без shell/инъекций; чистота DDD/детерминизм; без регрессий. Read-only. | `.4` |
| `.6` | **tech-writer** | `docs/architecture.md` (рус): `claude_code`-сессия (state-машина), worktree-изоляция, двойной гейт, нарратив stream-json, owner-команды, границы (никогда main/мерж). Gate. | `.5` |

## Волны (последовательно на одной ветке)

```
.1 домен+порты+стор → .2 инфра worktree/claude/gh → .3 use-case+owner-команды+нарратив → .4 test → .5 review(security) → .6 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-039`, один PR.
- Тесты — `.venv/bin/pytest` (uv run висит). **Реальный `claude` НЕ дёргаем в юнит-тестах** (фейк-runner).
  Гейт волны — КООРДИНАТОР через `.venv/bin/*`.

## Критерии готовности

- [ ] Owner ставит задачу → Боб через Claude Code делает её в изолированном worktree, наррирует,
      открывает **PR в ветку**; **никогда** не трогает main и не мержит сам (US-1..4).
- [ ] **Двойной гейт** соблюдён (без апрува плана нет исполнения; без owner нет мержа); kill-switch
      мгновенен; owner-only; `coder.enabled=false` дефолт.
- [ ] **Приват-инвариант:** Claude Code не видит SOUL/`bob.db`/`.env`/`config` (их нет в worktree);
      не в автономном safe-allowlist (US-5/owner-only).
- [ ] Без регрессий T3.A/диалога/authz/goals; cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
