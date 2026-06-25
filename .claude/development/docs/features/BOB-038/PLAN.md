<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-038 — T3.A⁺ «Архитектурный контекст»

> **Status:** Approved
> **Created:** 2026-06-25
> **Feature:** BOB-038 · родитель `bob-038`

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (порт git + домен-парсер) | Порт `RepoIntrospector.code_history(path)->str` (`domain/ports.py`). В `SubprocessRepoIntrospector` добавить `git` в `_allow` с **фикс-allowlist invocation-форм** (как `_BD_LIST_ARG_FORMS`): только `git log --oneline -- <path>` и `git log --grep=<BOB-key> --oneline` (опц. `-n <N>`); валидация `<path>` (внутри репо, не флаг) и `<BOB-key>` по шаблону; без произвольных флагов/подкоманд; таймаут+обрезка. Чистые домен-предикаты `parse_bead_refs(text)->list[str]` и `feature_doc_dir(key)->str` (`domain/introspection/`). Юнит-тесты (формы git, парсер, отказ произвольной подкоманды/`-C`/`show`/путь-инъекции). | — |
| `.2` | **dev** (навык + провязка) | `application/capabilities/code_rationale.py`: фабрика `make_code_rationale_capability(introspector)` (образец `inspect_architecture.py`), `permission="safe"`, вход `query`. `execute`: `code_history(query)` → `parse_bead_refs` → по ключам `list_tasks(key)` (=`bd show`) + `read_file` фича-дока (по `feature_doc_dir`, read-scope BOB-034) + `architecture_context(query)` (граф) → компактный «почему» + честное «не зафиксировано»; дедуп/лимит ключей+обрезка. Регистрация в `_build_registry` (`app.py`) при `introspection.enabled`; `git_bin` в конфиг/конструктор. **Не** в `goals.safe_capabilities`. | `.1` |
| `.3` | **test** | ≥80% + US-1..5 + приват-инвариант (навык не читает SOUL/`bob.db`/`.env`/`config`; git только фикс-формы) + честное «не зафиксировано» + границы стадии (не в safe-allowlist) + регрессии (T3.A навыки/tool-loop, BOB-034 read-scope). `.venv/bin/pytest`. | `.1,.2` |
| `.4` | **review** | Read-only/приват-инвариант не ослаблен; git-формы безопасны (без shell/инъекций/`git show`); связка код↔решения корректна; границы стадии; чистота DDD/детерминизм; без регрессий. Read-only. | `.3` |
| `.5` | **tech-writer** | `docs/architecture.md` (рус): навык `code_rationale`, связка код↔git↔беады↔фича-доки↔граф, git фикс-формы, место в T3.A. Gate. | `.4` |

## Волны (последовательно на одной ветке)

```
.1 порт+git-формы+парсер → .2 навык+провязка → .3 test → .4 review → .5 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-038`, один PR.
- Тесты — `.venv/bin/pytest` (uv run висит), один прогон. Гейт волны — КООРДИНАТОР через `.venv/bin/*`.

## Критерии готовности

- [ ] Боб отвечает на «почему этот код такой / что за решение» с опорой на реальную связку
      код↔беад↔PR↔фича-док↔граф (US-1..3); честное «не зафиксировано» при отсутствии (US-4).
- [ ] **Приват-инвариант** не ослаблен (US-5): навык не читает SOUL/`bob.db`/`.env`/`config`; git —
      только read-log фикс-формы. Read-only; не в `goals.safe_capabilities`.
- [ ] Без регрессий T3.A/BOB-034/tool-loop; cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
