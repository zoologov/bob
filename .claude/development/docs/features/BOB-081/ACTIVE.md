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
