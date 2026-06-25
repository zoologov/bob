<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-017 Phase A — «Боб знает свой мир»

> **Status:** Approved
> **Created:** 2026-06-25
> **Feature:** BOB-017 Phase A · родитель `bob-017`

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (приват-фундамент + порт + инфра) | `domain/introspection/privacy_guard.py`: чистый `PrivacyGuard(repo_root)` с DENY-инвариантом (`data/soul/**`, `data/bob.db*`, `.env*`, `config/**`; ALLOW только `src/`/`tests/`/`docs/`), предикаты `allows_path`/`sanitize`. Порт `RepoIntrospector` (Protocol) в `domain/ports.py` (`architecture_context`/`search_code`/`read_file`/`list_tasks`). `infrastructure/introspection/subprocess_introspector.py`: `SubprocessRepoIntrospector` через `asyncio.create_subprocess_exec` (фикс-allowlist read-подкоманд `beadloom ctx/graph/why/search`, `bd ready/show`; без shell; таймаут; обрезка вывода) + `read_file` через guard (путь проверяется ДО чтения). Юнит-тесты: guard DENY/ALLOW (обход невозможен), адаптер (allowlist/таймаут/обрезка/путь). | — |
| `.2` | **dev** (навыки + провязка + конфиг) | `application/capabilities/{inspect_architecture,read_code,list_work}.py`: фабрики `make_*_capability(introspector)` по образцу `recall_memory.py` (`permission="safe"`, JSON-Schema на 1 аргумент, `execute` делегирует в порт, компактный рендер, честный «не нашёл»). Регистрация в `_build_registry` (`app.py`) при `introspection.enabled`; конструирование `SubprocessRepoIntrospector(PrivacyGuard(...))`; добавить в persona `describe()`. Конфиг `introspection.{enabled=true, max_output_chars, read_max_lines, beadloom_bin, bd_bin}` → loader. **Не** добавлять в `goals.safe_capabilities`. | `.1` |
| `.3` | **test** | ≥80% + US-1..6 + **приват-инвариант** (SOUL/`bob.db`/`.env`/`config` → отказ, в облако не уходят) + честный «не нашёл» (US-5) + регрессии (`recall_memory`/`search_memory`/tool-loop целы; пустой/без-introspection registry → как раньше). Через `.venv/bin/pytest`. | `.1,.2` |
| `.4` | **review** | Read-only железно (нет записи/исполнения произвольного CLI/сети); приват-инвариант не обходится; граница стадии (навыки НЕ в автономном safe-allowlist); subprocess `exec` без shell + фикс-allowlist; чистота DDD/детерминизм; без регрессий. Read-only. | `.3` |
| `.5` | **tech-writer** | `docs/architecture.md` (рус): навыки самоинтроспекции за швом, `PrivacyGuard`/приват-инвариант, `RepoIntrospector`+subprocess-адаптер, место в рантайме, границы Phase A vs B/C. Gate. | `.4` |

## Волны (последовательно на одной ветке)

```
.1 приват+порт+инфра → .2 навыки+провязка+конфиг → .3 test → .4 review → .5 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-017`, один PR.
- Тесты — `.venv/bin/pytest` (uv run висит), один прогон за раз. Гейт каждой волны проверяет
  КООРДИНАТОР через `.venv/bin/*`.

## Критерии готовности

- [ ] Боб отвечает про свой код/архитектуру/процесс с опорой на реальные beadloom/код/Beads (US-1..4);
      честный «не нашёл» при пустом (US-5).
- [ ] **Приват-инвариант:** навыки никогда не читают/не передают в облако `SOUL.md`/`data/bob.db`/`.env`/
      `config/*`/`data/soul/*` — детерминированно на инфра-границе, не обходится промптом (US-6).
- [ ] Только чтение; навыки не в автономном safe-allowlist; `recall/search_memory`/tool-loop не сломаны.
- [ ] cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
