<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-023 — «Адресность»

> **Last updated:** 2026-06-23
> **Phase:** Development (автономный прогон до PR-merge)
> **Feature:** bob-0vh · branch `features/BOB-023`

---

## Текущий беад

**Беад:** `bob-0vh.4` — review (следующий).

## Прогресс

- [x] `.1` пламбинг (reply-to/@mention в MessageReceived + multibot) — зелёный (1240 passed)
- [x] `.2` детектор Addressivity + политика + SILENT — зелёный (1272 passed)
- [x] `.3` test — зелёный (1297 passed, cov 98%: addressivity 99% / handle_message 97%)
- [ ] `.4` review · `.5` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-0vh.1 | dev пламбинг | — | done |
| bob-0vh.2 | dev детектор+политика+SILENT | .1 | done |
| bob-0vh.3 | test | .1,.2 | done |
| bob-0vh.4 | review | .3 | in_progress |
| bob-0vh.3 | test | .1,.2 | blocked |
| bob-0vh.4 | review | .3 | blocked |
| bob-0vh.5 | tech-writer | .4 | blocked |

## Заметки

- **Автономный прогон** до PR-merge + перезапуска Боба (owner отошёл).
- Гейт каждой волны проверяет КООРДИНАТОР через `.venv/bin/pytest` (uv run висит; песочница агентов нестабильна).
- Dev-беады последовательно на одной ветке. Guardrails: прямое→всегда ответ; чужой 1:1→SILENT (интерес
  втягивает редко); гост-инвариант BOB-019 цел. Источник: PRD/RFC/CONTEXT.
