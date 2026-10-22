<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF — BOB-125: деплой по имени ветки брал локальную ветку VPS

> **Type:** bug · **Status:** Approved (P0, вскрыто выкаткой 2026-10-22; решение координатора — немедленный фикс, владелец мержит PR)
> **Created:** 2026-10-22 · **Беада:** `bob-7rm`

## Проблема

`deploy-bob.yml`: `git fetch` + `git checkout "$DEPLOY_REF"`. Для тега и SHA верно; для имени ветки `checkout main` берёт **локальную** ветку VPS, которую fetch не двигает. 22.10 две выкатки `ref=main` подряд выкатили старый код (VPS был `behind 7`): не доехали ни конфиг из #148, ни фикс BOB-124 (#149). Обнаружено по журналу: старт снова на 99 % CPU без строки бэкфилла.

## Решение

Если `refs/remotes/origin/<ref>` существует — `checkout -B <ref> origin/<ref>`; иначе прежний `checkout <ref>` (тег/SHA). Печать `rev-parse --short HEAD` в лог выкатки. Тест на НАСТОЯЩЕМ git: bare-origin на B, клон с локальной `main` на A → после скрипта деплоя HEAD == B; тест на тег — как прежде. Саботаж (старый checkout) — `test_a_deploy_by_branch_name_lands_the_origin_tip_not_the_stale_local_branch` FAILED.

## Axes

Изменение вне графа `src/bob` (workflow + `tests/deploy`); `beadloom impact` узлов не называет — оси пусты по построению, маршрут `bug`.

## Acceptance

- [x] тест на настоящем git зелёный, саботаж красный с именем
- [ ] PR → `main`, мёрж владельцем; следующая выкатка `ref=main` печатает `код на диске: <sha origin/main>`
