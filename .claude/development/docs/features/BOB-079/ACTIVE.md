# ACTIVE — BOB-079 Автобиографическая память

> **Focus:** первый срез self-model — Боб пишет и присваивает свои действия.

## Статус волн

| Волна | Беад | Роль | Статус |
|------|------|------|--------|
| 1 | bob-h10.1 | dev — ЯДРО self_action + порт + адаптер + флаг | ⏳ ready |
| 2 | bob-h10.2 | dev — CODING self-actions | ⛔ blocked(.1) |
| 3 | bob-h10.3 | dev — TOOL-LOOP self-actions | ⛔ blocked(.2) |
| 4 | bob-h10.4 | dev — READ surfaceable + voice присвоение | ⛔ blocked(.3) |
| 5 | bob-h10.5 | test — unit+BDD+mutation | ⛔ blocked(.4) |
| 6 | bob-h10.6 | review — качество/границы | ⛔ blocked(.5) |
| 7 | bob-h10.7 | tech-writer — docs | ⛔ blocked(.6) |

## Критический путь
.1 → .2 → .3 → .4 → .5 → .6 → .7 (линейно; dev последовательно — урок BOB-066).

## Живой смоук (после мержа + рестарта)
Свежая мини coding-сессия (start→stop) или форс runaway → эпизод `self_action` (первое лицо) в
`episodic_log` → «помнишь, что делал / инцидент?» → присвоение от первого лица + признание. S4: спросить
о несделанном → «не припоминаю за собой».

## Прогресс
- 2026-08-01: PRD/RFC/CONTEXT/PLAN approved; беады созданы (parent bob-h10); ветка features/BOB-079.
