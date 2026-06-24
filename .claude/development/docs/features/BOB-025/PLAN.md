<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-025 — «Адресность по непрерывности диалога (conversational floor)»

> **Status:** Approved
> **Created:** 2026-06-24
> **Feature:** BOB-025 · родитель `bob-v0k`

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (трекер + персист) | `domain/personality/conversation_floor.py`: `FloorHolder {BOB/OTHER/IDLE}`, `ConversationFloor` (holder/holder_id/since/idle_streak), чистые `advance_floor(floor, *, addressivity, sender_id, bob_replied, now, config)` (переход: DIRECTED_TO_BOB/ответ Боба→БОБ; DIRECTED_TO_OTHER→OTHER; AMBIENT при floor=БОБ→держит + idle_streak при молчании Боба; тайм-аут/streak→IDLE) и `resolve_addressivity(per_message, floor, *, now, config)` (AMBIENT+floor=БОБ-не-истёк→DIRECTED_TO_BOB). Порт `ConversationFloorStore` + Sqlite-impl (таблица на (chat_id,thread_id)). Юнит-тесты на переходы + резолв. | — |
| `.2` | **dev** (интеграция + конфиг) | В `handle_message` поверх BOB-023: per-message `classify_addressivity` → `load floor` → `resolve_addressivity` (эффективная адресность) → политика `decide_response` на ЭФФЕКТИВНОЙ → {SILENT/REACT/ENGAGE}; после хода `advance_floor` (bob_replied при ответе) → `save`. Конфиг `addressivity.floor.{enabled,timeout_seconds=300,reset_after_silent=2}` → `app.py`. | `.1` |
| `.3` | **test** | ≥80% + US-1..5 + guardrails (непрерывность owner+гость пока floor=БОБ; поворот к другому→Боб отступает; распад тайм-аут/streak; прямое всегда к Бобу; не-перехват чужого пока floor НЕ у Боба) + регрессии (BOB-023 SILENT/политика, гость-инвариант, BOB-026 анти-повтор). `.venv/bin/pytest`. | `.1,.2` |
| `.4` | **review** | Непрерывность работает (US-1..5); не-перехват чужого диалога цел; распад корректен; прямое всегда к Бобу; гость-инвариант по правам не ослаблен; чистота/детерминизм по `now`; без регрессий. Read-only. | `.3` |
| `.5` | **tech-writer** | `docs/architecture.md` (рус): трекер conversation_floor, переходы, резолв-поверх-BOB-023, персист, дефолты, BobNet turn-taking. Gate. | `.4` |

## Волны (последовательно на одной ветке)

```
.1 трекер+персист → .2 интеграция+конфиг → .3 test → .4 review → .5 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-025` (уже с main),
  один PR. Тесты — `.venv/bin/pytest` (uv run висит), один прогон за раз. Гейт каждой волны —
  КООРДИНАТОР через `.venv/bin/*`.

## Критерии готовности

- [ ] Owner и гость общаются с Бобом **без метки в каждом сообщении**, пока «у микрофона» Боб
      (непрерывность от любого участника); прямое обращение — всегда.
- [ ] **Цель BOB-023 цела:** Боб не встревает в чужой диалог (безметочное → к Бобу только пока он
      держит реплику); поворот к другому и распад снимают реплику.
- [ ] Гость-инвариант BOB-019 по правам не ослаблен; BOB-023 SILENT/политика и BOB-026 анти-повтор
      не сломаны; cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
