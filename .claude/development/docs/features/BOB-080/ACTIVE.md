# ACTIVE — BOB-080 Ростер комнаты

> **Focus:** припоминание состава комнаты по социальному поводу (без подсказки имён).

## Статус волн

| Волна | Беад | Роль | Статус |
|------|------|------|--------|
| 1 | bob-dct.1 | dev — DATA+ДОМЕН (recent-запрос + display_name + roster.py + флаг) | ⏳ ready |
| 2 | bob-dct.2 | dev — USECASE+READ (RosterRecall + voice-директива) | ⛔ blocked(.1) |
| 3 | bob-dct.3 | test — unit+BDD+mutation | ⛔ blocked(.2) |
| 4 | bob-dct.4 | review — качество/границы | ⛔ blocked(.3) |
| 5 | bob-dct.5 | tech-writer — docs | ⛔ blocked(.4) |

## Критический путь
.1 → .2 → .3 → .4 → .5 (линейно; dev последовательно — общие касания social/voice/wiring).

## Живой смоук (после мержа + рестарта)
«как тебе новенькие?» → Боб называет недавних (Лиля/Паша) САМ, без имён-подсказок; старожилов не подаёт
как новых; пустой ростер → «новеньких не припомню» (INV-1/S4).

## Прогресс
- 2026-08-01: PRD/RFC/CONTEXT/PLAN approved; беады созданы (parent bob-dct); ветка features/BOB-080.
- 2026-08-01: ✅ ЗАВЕРШЁН. Все беады закрыты (+ fix-цикл .6/.7 по review-Major). PR #112 смержен (52cc10e).
  pytest 4414, mutation 94.9% на roster.py, review OK (после fix), beadloom ci PASS, mypy src+tests clean.
  Флаг social.roster=true; Боб перезапущен (pid 22455). 🔴 ЖИВОЙ СМОУК на реальных данных: viewer=owner →
  ростер поднял Лилю+Павла (newcomer, 0д), Алексея/Norman (31/38д) — не как новых; директива назвала
  ТОЛЬКО новичков (fix подтверждён), имена через note-parse fallback. S1/S2 доказаны end-to-end.
