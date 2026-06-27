<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-045 — «Память диалога по персоне + длинные паузы»

> **Status:** Approved
> **Created:** 2026-06-26

---

## Беады (DAG)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** | Атрибуция + read-шов: колонка `sender_id` в `episodic_log` (идемпотентная миграция `ALTER ADD COLUMN` + `PRAGMA` проверка + индекс `(sender_id, ts)`); `_persist` пишет `event.sender_id`; `recent_episodes_for(sender_id, k)`; `sender_id` в recalled-проекции; best-effort бэкафилл по имени-префиксу (owner-имя→owner_id, allowlist-имена→id). Юнит-тесты. | — |
| `.2` | **dev** | `handle_message`: per-person history (`recent_episodes_for(interlocutor.sender_id, recent_turns)`) для owner/known/guest; recall — owner глобальный, non-owner пост-фильтр по `sender_id`; сохранить прочие гостевые ограничения; деградация без sender_id-шва. Юнит-тесты. | `.1` |
| `.3` | **dev** | Длинные паузы: опц. лёгкий маркер «давно не виделись» из ts последнего хода персоны (чистый domain-helper) + конфиг `dialogue.absence_hint_hours` (~8ч, опц.); подсказка в compose-контекст (не скрипт фразы). Юнит-тесты. | `.1,.2` |
| `.4` | **test** | ≥80% + US-1..5: нить гостя; длинная пауза подхватывается; мульти-парти (две нити не путаются); 🔴 ПРИВАТ-ИНВАРИАНТ (при guest нет ни одного эпизода/recall с чужим `sender_id`); миграция идемпотентна + бэкафилл; absence-hint; регрессии (BOB-044 окно/anti-repeat/recall-grounding/BOB-019 authz/owner-диалог). | `.1,.2,.3` |
| `.5` | **review** | 🔴 SECURITY: приват-инвариант defense-in-depth (история-фильтр + recall пост-фильтр); authz BOB-019 не ослаблен; гостевой ход не в owner-факты; миграция безопасна/идемпотентна; DDD; без регрессий. Read-only. | `.4` |
| `.6` | **tech-writer** | `architecture.md` (рус): per-person память, `sender_id`/миграция, authz-safe гость, длинные паузы. Gate. | `.5` |

## Критический путь

```
.1 атрибуция+read-шов → .2 per-person history+scoped recall → .3 длинные паузы → .4 test → .5 review → .6 tech-writer
```

## Волны

- Волна 1: `.1` (атрибуция/миграция/read-шов).
- Волна 2: `.2` (per-person wiring) → `.3` (паузы).
- Волна 3: `.4` test → `.5` review → `.6` tech-writer.

## Критерии готовности

- [ ] Боб держит личную нить с owner и гостем; длинная пауза не теряет тему; мульти-парти — две нити.
- [ ] 🔴 Приват-инвариант: non-owner не видит чужой/owner-приватной памяти; authz не ослаблен.
- [ ] Миграция идемпотентна + бэкафилл best-effort; без регрессий; cov ≥80%; ruff/mypy --strict/beadloom ci зелёные.

## Живой прогон (после мержа)

- 🔴 Бэкап `data/bob.db` перед рестартом (миграция + бэкафилл по живой БД).
- Рестарт Боба → проверить миграцию (колонка/индекс), бэкафилл, отсутствие регрессий.
