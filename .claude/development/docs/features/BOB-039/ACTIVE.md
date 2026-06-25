<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-039 — T3.B «Боб запускает Claude Code» (гейтед)

> **Feature:** BOB-039 · родитель `bob-3ro` · ветка `features/BOB-039`
> **Обновлено:** 2026-06-26

---

## Фокус

Гейтед `claude_code`-сессия: Боб делает dev-задачи owner в изолированном worktree, наррирует, branch+PR, двойной гейт.

## Беады

| Беад | Роль | Статус | Зависит |
|------|------|--------|---------|
| `bob-3ro.1` | dev — домен coding/ (машина+narrate) + порты + стор | ready | — |
| `bob-3ro.2` | dev — инфра worktree/claude/gh | blocked | .1 |
| `bob-3ro.3` | dev — use-case CodingAssistant + owner-команды + нарратив | blocked | .1,.2 |
| `bob-3ro.4` | test — US-1..6 + гейты + never-main + owner-only + приватность | blocked | .1,.2,.3 |
| `bob-3ro.5` | review — SECURITY-проход | blocked | .4 |
| `bob-3ro.6` | tech-writer | blocked | .5 |

## Критический путь

```
.1 домен+порты+стор → .2 инфра → .3 use-case+owner-команды → .4 test → .5 review(security) → .6 tech-writer
```

## Прогресс

- 2026-06-26 — PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; запуск координатора.

## Инварианты (🔴 security)

- Изоляция worktree: личных данных (SOUL/`bob.db`/`.env`/`config`) НЕТ в worktree (gitignored, проверено).
- Только ветка+PR, НИКОГДА main; use-case без пути в main / `gh pr merge`; мержит owner.
- Двойной гейт: EXECUTING только из PLAN_READY по owner-команде; owner-only; kill-switch.
- `coder.enabled=false` дефолт; не в `goals.safe_capabilities`. Реальный claude в юнит-тестах не дёргаем.
- `.venv/bin/pytest` (uv run висит); ≥80%; ruff/mypy --strict/beadloom ci зелёные.
