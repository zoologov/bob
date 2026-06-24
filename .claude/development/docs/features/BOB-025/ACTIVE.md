<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-025 — «Адресность по непрерывности диалога»

> **Last updated:** 2026-06-24
> **Phase:** Development (автономный прогон до PR-merge + перезапуска Боба)
> **Feature:** bob-v0k · branch `features/BOB-025` (синхр. с main 21b023d)

---

## ⏸️ ПАУЗА (по запросу owner, 2026-06-24)

**Возобновление — СНАЧАЛА эти 2 шага, потом волны .4/.5:**
1. **Фикс резилентности (найден тестами .3):** `_resolve_effective_addressivity` (handle_message.py ~1342)
   — `floor_store.load` НЕ обёрнут best-effort (в отличие от `_advance_floor_after_turn` 1370-1383).
   Падение стора при резолве ломает весь ход (Боб молчит), вопреки RFC «floor best-effort».
   **Сделать:** обернуть load в `try/except Exception → return per_message` + `logger.exception`
   (зеркало advance-стороны 1382-1383).
2. **Перевернуть тест** `test_floor_store_resolve_load_failure_propagates` (test_handle_message.py ~3886)
   → assert «ход НЕ падает, Боб отвечает через per_message» (сейчас он pin'ит баг через pytest.raises;
   помечен «production observation»). Затем `.venv/bin/pytest` зелёный → закрыть `.3` → волна `.4` review.

## Прогресс

- [x] `.1` трекер conversation_floor + персист — зелёный (1584 passed)
- [x] `.2` интеграция в handle_message + конфиг — зелёный (1599 passed)
- [x] `.3` test — тесты готовы, зелёный (1611 passed; cov 98%, floor 100%); нашёл баг резилентности (см. шаг 1 выше) — фикс на возобновлении ДО закрытия .3
- [ ] `.4` review · `.5` tech-writer · PR #29 · merge · перезапуск

## Статусы беадов

| Беад | Роль | Зависит | Статус |
|------|------|---------|--------|
| bob-v0k.1 | dev трекер+персист | — | done |
| bob-v0k.2 | dev интеграция+конфиг | .1 | done |
| bob-v0k.3 | test | .1,.2 | in_progress (тесты зелёные; ждёт фикс резолв-load + переворот теста) |
| bob-v0k.4 | review | .3 | blocked |
| bob-v0k.5 | tech-writer | .4 | blocked |
| bob-v0k.3 | test | .1,.2 | blocked |
| bob-v0k.4 | review | .3 | blocked |
| bob-v0k.5 | tech-writer | .4 | blocked |

## Заметки

- **Автономный прогон** до PR-merge + перезапуска Боба.
- Модель: floor=БОБ (держит реплику) → безметочное от любого → к Бобу; поворот к другому→OTHER;
  распад тайм-аут 300с / 2 молчаливых хода. Привязка к АДРЕСАТУ, не к говорящему.
- Не ломать: BOB-023 (SILENT/политика/others_present), BOB-019 гость-инвариант, BOB-026 анти-повтор.
- Гейт каждой волны — КООРДИНАТОР через `.venv/bin/pytest` (uv run висит; при обрыве — инлайн).
