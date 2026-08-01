# ACTIVE — BOB-081 Dev-интроспекция (git + трекер, read-only)

> **Focus:** Боб может заглянуть в git-историю и трекер (read-only) и заземлить разговор о работе.

## Статус волн

| Волна | Беад | Роль | Статус |
|------|------|------|--------|
| 1 | bob-0gj.1 | dev — DATA+ЯДРО (dev_query + git/bd формы + порт) | ⏳ ready |
| 2 | bob-0gj.2 | dev — TOOLS+ФЛАГ (capability-обёртки + introspection.dev_tools) | ⛔ blocked(.1) |
| 3 | bob-0gj.3 | test — unit+BDD+mutation | ⛔ blocked(.2) |
| 4 | bob-0gj.4 | review — SECURITY+границы | ⛔ blocked(.3) |
| 5 | bob-0gj.5 | tech-writer — docs | ⛔ blocked(.4) |

## Критический путь
.1 → .2 → .3 → .4 → .5 (линейно; dev последовательно — общие касания интроспектор/wiring).

## Живой смоук (после мержа + активации флага)
owner «глянь последние 10 коммитов» → реальные [BOB-08x]; «покажи закрытые/в работе задачи» → реальные
беады; «комментарии к BOB-076» → чекпоинты. 🔴 Негативный: вывод git/bd без секретов; write-формы (bd
close/git commit) недоступны.

## Прогресс
- 2026-08-01: PRD/RFC/CONTEXT/PLAN approved; беады созданы (parent bob-0gj); ветка features/BOB-081.
- 2026-08-01: ✅ ЗАВЕРШЁН. Все беады закрыты. PR #113 смержен (89b6096). pytest 4550, mutation 100% на
  dev_query, security-review OK (ни одной выразимой записи/инъекции/утечки/гостевого доступа), beadloom
  ci PASS, mypy src+tests clean. Флаги introspection.enabled+dev_tools=true; Боб перезапущен (pid 58466).
  🔴 ЖИВОЙ СМОУК на реальном репо: S1 recent_commits→реальные коммиты; S2 tasks_by_status(closed)→реальные
  беады; S3 task_comments→реальные чекпоинты; НЕГАТИВ: инъекция show_task('--upload-pack=x')→ValueError
  refused. S1/S2/S3 + read-only доказаны end-to-end.
