# ACTIVE — BOB-084 Кодер-runner падает на stream-json >64 КБ

> **Focus:** limit= в спавнерах + резилентная читалка + тест на реальном subprocess.

| Волна | Беад | Роль | Статус |
|------|------|------|--------|
| 1 | bob-a2c.1 | dev — limit + резилентная read_lines | ⏳ ready |
| 2 | bob-a2c.2 | test — реальный subprocess >64 КБ | ⛔ blocked(.1) |
| 3 | bob-a2c.3 | review | ⛔ blocked(.2) |

## Живой смоук
`/code -i` из лички → реальная claude-сессия НЕ обрывается на первом крупном эвенте.

## Прогресс
- 2026-08-02: BRIEF approved; беады (parent bob-a2c); ветка features/BOB-084.
