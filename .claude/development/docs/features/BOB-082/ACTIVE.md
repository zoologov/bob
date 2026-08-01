# ACTIVE — BOB-082 Dev-канал в личке (лайв-стрим + сквозная память)

> **Focus:** dev-режим в личке с живым стримом Claude Code; Боб — один разум across личка+группа.

## Статус волн

| Волна | Беад | Роль | Статус |
|------|------|------|--------|
| 1 | bob-pdo.1 | dev — КАНАЛ+SCOPE (chat_type сигнал + scope по месту) | ⏳ ready |
| 2 | bob-pdo.2 | dev — AUTHZ owner-DM | ⛔ blocked(.1) |
| 3 | bob-pdo.3 | dev — ЛАЙВ-СТРИМ в личку + флаг | ✅ dev-done (in_progress, ждёт coordinator) |
| 4 | bob-pdo.4 | dev — КОНСЕНТ-РАСКРЫТИЕ | ⛔ blocked(.3) |
| 5 | bob-pdo.5 | test — unit+BDD+mutation | ⛔ blocked(.4) |
| 6 | bob-pdo.6 | review — SECURITY+PRIVACY | ⛔ blocked(.5) |
| 7 | bob-pdo.7 | tech-writer — docs | ⛔ blocked(.6) |

## Критический путь
.1 → .2 → .3 → .4 → .5 → .6 → .7 (линейно; dev последовательно — общие касания gateway/handle/disclosure).

## Живой смоук (после мержа + активации флага)
`/code` из лички → живой стрим в личку; группа чистая (указатель); память сквозная (в личке про группу и
наоборот); S5 «расскажи ребятам про X» в группе → раскрывает; без спроса — молчит; S6 гость не получает
dev-канал. 🔴 Feasibility: бот пишет в DM (owner нажал Start).

## Прогресс
- 2026-08-01: PRD/RFC/CONTEXT/PLAN approved; беады созданы (parent bob-pdo); ветка features/BOB-082.
