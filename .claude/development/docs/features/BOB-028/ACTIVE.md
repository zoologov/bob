<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-028 — «T2.2 Self-Improvement»

> **Last updated:** 2026-06-24
> **Phase:** Development (автономный прогон до PR-merge + перезапуска Боба)
> **Feature:** bob-7xn · branch `features/BOB-028`

---

## Текущий беад

**Беад:** `bob-7xn.5` — review: безопасность по конструкции (следующий).

## Прогресс

- [x] `.1` модель правила + persist — зелёный (Lever-allowlist без рычага безопасности)
- [x] `.2` детектор паттернов — зелёный (1681 passed; только PROPOSED, рычаг из allowlist)
- [x] `.3` апрув-флоу + мягкое применение — зелёный (1720 passed; наклон-не-перехват; OFF default)
- [x] `.4` test — зелёный (1749 passed; cov 98%, BOB-028-модули 100%; safety-инварианты ДОКАЗАНЫ: свип состояний, allowlist по конструкции, наклон-не-перехват, owner-only, OFF)
- [ ] `.5` review · `.6` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-7xn.1 | dev модель+persist | — | done |
| bob-7xn.2 | dev детектор | .1 | done |
| bob-7xn.3 | dev апрув+применение | .1,.2 | done |
| bob-7xn.4 | test | .1,.2,.3 | done |
| bob-7xn.5 | review | .4 | in_progress |
| bob-7xn.4 | test | .1,.2,.3 | blocked |
| bob-7xn.5 | review | .4 | blocked |
| bob-7xn.6 | tech-writer | .5 | blocked |

## Заметки

- **Автономный прогон** до PR-merge + перезапуска Боба.
- **🔴 Safety-ядро (тесты .4, ревью .5):** граница по конструкции — `Lever`-allowlist не содержит
  authz/гостя/SOUL/safety (defense-in-depth домен+применение); authz-before-autonomy (без апрува
  ничего не применяется); ограниченность/обратимость; OFF по умолчанию.
- Реюз: ReflectTick (BOB-026), апрув-паттерн Goal Engine (BOB-015), voice/verbosity/urge/адресность
  как точки применения. Мотив-пример: Боб сам замечает застрявшее настроение и предлагает поправку.
- Гейт каждой волны — КООРДИНАТОР через `.venv/bin/pytest` (uv run висит; при обрыве — инлайн).
