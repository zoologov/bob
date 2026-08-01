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
- 2026-08-01: .4 ИНТЕЙК-РЕЖИМ ГОТОВ (dev). Реализовано: (1) чистые предикаты
  `src/bob/coding/interactive_intent.py` (parse_interactive_entry `/code -i`/`/interactive`;
  is_interactive_exit — deliberate точное совпадение, не хайджек steer); (2)
  `src/bob/coding/usecases/interactive_intake.py` InteractiveIntakeRouter — owner+DM+active-гейт,
  open/feed/stop + mode-line notifier (INV-5); (3) PreComposeGate.maybe_route_interactive
  (прокинут is_group, резилентность); (4) handle_message: гейт ПЕРЕД maybe_route_coding;
  (5) wiring _build_interactive_intake + композиция → HandleMessage; (6) флаг coder.interactive
  в bob.example.yaml. Тесты: 37 новых (домен 27 / роутер 8 / wiring 2) + 4 интеграционных в
  test_handle_message. Полный прогон 4757 pass; ruff+mypy(src+tests) чисто; lint --strict 0 violations.
  ⏭ .5 test: BDD S1/S2/S4/S5 + mutation ≥85% на interactive_intent предикатах.
