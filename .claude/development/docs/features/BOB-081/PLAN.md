> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-081

# PLAN — BOB-081 (DAG + seam-точки)

## Seam-точки (авторитетно, из разведки)

- Реестр: `capabilities/usecases/registry.py:45/112`; контракт `capabilities/ports.py:168`. Зеркало
  инструмента — `capabilities/usecases/list_dir.py:35-86`. Регистрация — `runtime/wiring/capabilities.py:93-105`.
- Интроспектор: порт `capabilities/ports.py:266/328/337`; адаптер
  `capabilities/adapters/introspection/subprocess_introspector.py` (git `_GIT_SUBCOMMANDS:65`, форма
  `_validate_git_args:558`; bd `_BD_SUBCOMMANDS:62`, статусы `:71`; `_run:511`, санитайз `:529`, timeout `:105`).
- Санитайз (наследуется): `capabilities/introspection/privacy_guard.py:148`.
- Флаг: `runtime/wiring/parameters.py:458` (`_build_introspection_enabled`) → под-флаг рядом; бинарники
  `infrastructure/config/loader.py:309` + `wiring/capabilities.py:145`; дефолт-конфиг `config/bob.example.yaml`.
- Гейт: `personality/usecases/voice_composer.py:357` (`is_guest`). Возврат: `capabilities/usecases/tool_loop.py:199/276`.
- Ядро: **новый** `capabilities/introspection/dev_query.py` (pure).

## Беады

```
BOB-081 [feature] — dev-интроспекция: git-история + трекер (read-only)
├── .1 [dev] — DATA+ЯДРО: dev_query.py (clamp_commit_count/validate_bead_id/normalize_status, pure) +
│              расширить subprocess_introspector: repo-wide `git log -n N` форма + `bd comments`
│              подкоманда + порт-методы recent_commits/task_comments/show_task/list_tasks(status).
│              Write-подкоманды НЕ добавлять. Санитайз/timeout наследуются.
├── .2 [dev] — TOOLS+ФЛАГ: capability-обёртки recent_commits/list_tasks/show_task/task_comments (зеркало
│              list_dir.py) + под-флаг introspection.dev_tools (default OFF) + регистрация в
│              wiring/capabilities.py. Реконсилить с существующим list_work (не плодить дубль). deps .1
├── .3 [test] — unit (dev_query границы/инъекции; интроспектор fake-runner: новые формы + 🔴 ОТКАЗ
│              write-подкоманд bd close/git commit/git show + arg-инъекций; санитайз на выводе) + BDD
│              (S1 commits / S2 list по статусу / S3 show+comments / S5 пусто-честно + guest-без-инструментов)
│              + mutation ≥85% на dev_query.py. deps .2
├── .4 [review] — 🔴 SECURITY: read-only жёстко (ни одна мутирующая форма не выразима); санитайз на git/bd
│              выводе; guest без инструментов; allowlist тесен; инъекция id/флагов невозможна; INV-1..6;
│              DDD (dev_query I/O-free). deps .3
└── .5 [tech-writer] — docs (capabilities: git/tracker read-only инструменты + флаг introspection.dev_tools
                     + read-only/санитайз/authz-гейт). deps .4
```

## Волны / критерии

Dev последовательно (.1→.2 — общие касания интроспектор/wiring; урок BOB-066). Test → review → tw → PR →
self-merge → рестарт → живой прогон.

🔴 **Живой смоук (после активации флага):** owner «глянь последние 10 коммитов» → реальные [BOB-08x];
«покажи закрытые задачи» / «что в работе» → реальные беады нужного статуса; «комментарии к BOB-076» →
чекпоинты. 🔴 **Негативный смоук:** вывод git/bd на РЕАЛЬНОМ репо не содержит секретов; write-формы
(`bd close`/`git commit`) недоступны. Ядро `dev_query.py` mutation ≥85%.

## Риски (из RFC)

- Утечка секретов → санитайз `_run` + живой негативный смоук (урок BOB-067).
- Прорыв к write → allowlist подкоманд/форм; ревью-беад проверяет невыразимость мутаций; unit на отказ.
- Инъекция аргументов → validate_bead_id/_looks_like_flag + exec без shell.
- Гость получил доступ → тест на is_guest-гейт.
- Флуд → count кап ≤50 + 30s timeout + truncate.
