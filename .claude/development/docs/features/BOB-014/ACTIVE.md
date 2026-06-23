<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-014 — «Отношения (multi-party) + обида/охлаждение» (T1.5)

> **Last updated:** 2026-06-23
> **Phase:** Done (все волны закрыты — **закрывает Тир 1**)
> **Epic:** bob-8id · branch `features/BOB-014`

---

## Текущий беад

**Нет активного беада.** Все волны закрыты: dev (.1/.2a/.2b) → test → review →
tech-writer. `docs/architecture.md` обновлён (новая секция «Отношения и обида
(BOB-014)»). **Закрывает Тир 1.**

### План .2b — ГОТОВО (dev)
1. [x] `domain/personality/sulk.py` (чистый): `SulkState`/`SulkConfig` + `observe_relationship` (порог+устойчивость, идемпотентность) + `recover` (гарант. выход по времени, тепло ускоряет, чистит announced).
2. [x] `domain/personality/profanity.py` (чистый): `is_directed_hostility` — спокоен к casual-мату, ловит направленные оскорбления.
3. [x] `governance.py`: `ProactiveHistory.sulk_active` veto (default False).
4. [x] `voice.py`: `sulk_directive()` (холодно-но-всё-ещё-Боб, не грубо, не reset) + `profanity_stance()`.
5. [x] Персист: порт `SulkStore` + таблица `sulk_state` + `SqliteSulkStore`.
6. [x] Восстановление на reflect-тике (`SulkRecoveryStep` + `SulkRecoverer` seam в `ReflectTick`).
7. [x] GUPPI announce one-shot при входе (`GuppiHandler.announce_sulk` + `SulkAnnouncer` seam).
8. [x] Композиция в app.py; холодный тон при sulk в `HandleMessage`; guest-disengage через знаковый `_relationship_bar_shift` (.2a DECLINE при cratered-отношении); sulk-veto в `ProactivityEngine`.

### Гейт (dev)
- `.venv/bin/pytest` = **1226 passed**; `mypy --strict` (src+tests) clean; `ruff` clean; `beadloom lint --strict` = 0 violations.
- `sync-check` rc=2: `docs/architecture.md` устарел эпик-широко (включая нетронутые модули) — рефреш — задача tech-writer (.5).

## Прогресс

- [x] `.1` RelationshipTracker (per-sender) + влияние на тон/уступчивость
- [x] `.2a` Аппетит к разговору: EngagementLevel (FULL/PLAYFUL/TERSE/DECLINE) ×
      mood/topic-interest/fatigue/relationship + feedback (mood↑, fatigue↑/↓)
- [x] `.2b` (bob-8id.6) Обида/Sulk + guest-disengage + восприятие мата
- [x] `.3` test · `.4` review · `.5` tech-writer (`docs/architecture.md`)

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-8id.1 | dev RelationshipTracker | — | done |
| bob-8id.2 | dev Обида/Sulk | .1 | done |
| bob-8id.3 | test | .1,.2 | done |
| bob-8id.4 | review | .3 | done |
| bob-8id.5 | tech-writer | .4 | done |

## Заметки

- Dev-беады **последовательно** на одной ветке (фоновые агенты, общий tree).
- Guardrails: отношения в [-1,1]+дрейф; обида не по мелочи + **гарантированный выход** (intensity→0 по
  времени) + идемпотентность; **память цела (anti-Exodus, без reset)**. Как характер.
- Sulk v1 — на owner-отношении. Источник: PRD/RFC/CONTEXT. **Закрывает Тир 1.**
