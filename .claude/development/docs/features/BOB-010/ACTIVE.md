<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-010 — Эпик «Живой Боб» (Фаза 1 — Проактивность)

> **Last updated:** 2026-06-20
> **Phase:** Development — Фаза 1
> **Epic:** bob-uns · branch `features/BOB-010`

---

## Текущий беад

**Беад:** bob-uns.1 — dev: domain (UrgeModel + SocialEnergy + Governance + порт), W1.

## Прогресс

- [ ] W1: bob-uns.1 (domain-движок) — старт

## Статусы беадов (Фаза 1)

| Беад | Роль | Зависит от | Статус |
|------|------|-----------|--------|
| bob-uns.1 | dev: domain (Urge/Energy/Governance/порт) | — | open (ready) |
| bob-uns.2 | dev: ProactivityEngine + ProactiveTick | .1 | blocked |
| bob-uns.3 | dev: стор + /quiet,/wake в GUPPI | .1 | blocked |
| bob-uns.4 | dev: интеграция app.py + e2e | .2,.3 | blocked |
| bob-uns.5 | test | .4 | blocked |
| bob-uns.6 | review | .5 | blocked |
| bob-uns.7 | tech-writer (+ VISION принципы) | .6 | blocked |

**Волны:** W1 {.1} → W2 {.2, .3} ∥ → W3 {.4} → .5 → .6 → .7.

## Заметки

- Принцип: человечность = состояние, управляющее тоном/содержанием/временем; НЕ трюки (анти-цели запрещены).
- Drive-модель порыва + стохастика; лимиты = только потолок. Всё per-persona; Clock/seed инъекция; локальное TZ.
- Постит в Bob/32; owner-команды в GUPPI (Main). Топология: Bobiverse / Main=GUPPI / Bob=32 / BobNet=future.
- Фазы 2/3 — беады на старте фазы (после live-тюнинга Ф1).
