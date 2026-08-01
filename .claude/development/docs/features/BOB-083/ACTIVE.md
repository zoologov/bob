# ACTIVE — BOB-083 Интерактивный терминал Claude Code в личке (T3.C⁺)

> **Focus:** двусторонний интерактив — owner steer'ит claude из лички; фундамент: входящий DM доходит.

## Статус волн

| Волна | Беад | Роль | Статус |
|------|------|------|--------|
| 1 | bob-443.1 | dev — ФУНДАМЕНТ (owner-DM доходит + reply в личку) | ⏳ ready |
| 2 | bob-443.2 | dev — RUNNER (персистентный open-stdin) | ⛔ blocked(.1) |
| 3 | bob-443.3 | dev — СЕССИЯ (INTERACTIVE state + прямой kill) | ⛔ blocked(.2) |
| 4 | bob-443.4 | dev — ИНТЕЙК-РЕЖИМ (реплики→stdin + команды) | ⛔ blocked(.3) |
| 5 | bob-443.5 | test — unit+BDD+mutation | ⛔ blocked(.4) |
| 6 | bob-443.6 | review — SECURITY | ⛔ blocked(.5) |
| 7 | bob-443.7 | tech-writer — docs | ⛔ blocked(.6) |

## Критический путь
.1 → .2 → .3 → .4 → .5 → .6 → .7 (линейно; dev последовательно — общие касания multibot/coding/intake).

## Живой смоук (после мержа + активации флага)
🔴 Боб шлёт owner'у в личку **краткий отчёт** (тест DM-выхода). Затем `/code -i` из лички → живой стрим +
steer репликой + `stop`→kill+возврат к обычному Бобу. Негатив: гость/группа не открывают; main недостижим.

## Прогресс
- 2026-08-01: PRD/RFC/CONTEXT/PLAN approved; беады созданы (parent bob-443); ветка features/BOB-083.
