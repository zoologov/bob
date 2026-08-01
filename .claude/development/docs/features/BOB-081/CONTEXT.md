> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-081

# CONTEXT — BOB-081 Dev-интроспекция (git + трекер, read-only)

## Суть

Боб получает read-only разговорные инструменты: git-история (последние коммиты) + трекер beads (списки
по статусам / детали / комментарии). Отвечает своими словами. За под-флагом `introspection.dev_tools`.

## Ключевые решения (из RFC)

- Каркас переиспользуем (BOB-067): реестр/tool-loop/возврат модели/**санитайз на всём выводе**/гейт
  `is_guest` (гость без инструментов) — INV-3 и INV-4 бесплатно.
- Доделать узко: repo-wide `git log -n N`, `bd comments`, тонкие обёртки, чистое ядро валидации.
- **Ядро** `capabilities/introspection/dev_query.py` (pure): `clamp_commit_count`/`validate_bead_id`/
  `normalize_status` — mutation ≥85%; данные в subprocess только через предикаты.
- **DATA:** новые allowlist-формы в `subprocess_introspector.py` + порт-методы `recent_commits`/
  `task_comments`/`show_task`/`list_tasks(status)`. Write-подкоманды НЕ добавляются (жёсткий INV-1).
- **TOOLS:** capability-обёртки (зеркало list_dir.py) `recent_commits/list_tasks/show_task/task_comments`.
- **Флаг** `introspection.dev_tools` (default OFF → ON в running-config после ревью).
- 🔴 Безопасность: read-only allowlist + санитайз + живой негативный смоук (урок BOB-067/BOB-076).

## Инварианты (из PRD)

INV-1 read-only · INV-2 заземление не дамп · INV-3 без секретов · INV-4 authz (гость нет) · INV-5
честность · INV-6 bd read-only CLI.

## Стандарты кода (CLAUDE.md §0.1)

Python 3.12+ asyncio · DDD/Clean (domain I/O-free; порты; адаптеры) · TDD · BDD `.feature` · mutation
≥85% на ядре · ruff · mypy --strict (src+tests!) · без print/breakpoint/bare-except/мутабельных дефолтов ·
subprocess только `exec` (не shell) · beadloom reindex/sync-check/lint перед коммитом.

## Границы

Никакой записи (git/bd), без coder, без дашбордов, без проактивного лазанья.

## Связи

[[bob-079-autobiography]] (пара-enabler, заземляет автобиографию) · [[bob-067-repo-navigation]]
(навигация/санитайз/гейт переиспользуем) · [[bob-076-coder-runaway]] (мощное не через эти инструменты;
read-only) · BOB-038 (интроспектор git).
