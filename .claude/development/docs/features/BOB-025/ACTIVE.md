<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-025 — «Адресность по непрерывности диалога»

> **Last updated:** 2026-06-24
> **Phase:** Development (автономный прогон до PR-merge + перезапуска Боба)
> **Feature:** bob-v0k · branch `features/BOB-025` (синхр. с main 21b023d)

---

## Текущий беад

**Беад:** `bob-v0k.3` — test: US-1..5 + guardrails (следующий).

## Прогресс

- [x] `.1` трекер conversation_floor + персист — зелёный (1584 passed)
- [x] `.2` интеграция в handle_message + конфиг — зелёный (1599 passed; _AddressivityDecision, advance/save на всех путях, enabled-флаг)
- [ ] `.3` test · `.4` review · `.5` tech-writer

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-v0k.1 | dev трекер+персист | — | done |
| bob-v0k.2 | dev интеграция+конфиг | .1 | done |
| bob-v0k.3 | test | .1,.2 | in_progress |
| bob-v0k.3 | test | .1,.2 | blocked |
| bob-v0k.4 | review | .3 | blocked |
| bob-v0k.5 | tech-writer | .4 | blocked |

## Заметки

- **Автономный прогон** до PR-merge + перезапуска Боба.
- Модель: floor=БОБ (держит реплику) → безметочное от любого → к Бобу; поворот к другому→OTHER;
  распад тайм-аут 300с / 2 молчаливых хода. Привязка к АДРЕСАТУ, не к говорящему.
- Не ломать: BOB-023 (SILENT/политика/others_present), BOB-019 гость-инвариант, BOB-026 анти-повтор.
- Гейт каждой волны — КООРДИНАТОР через `.venv/bin/pytest` (uv run висит; при обрыве — инлайн).
