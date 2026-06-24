<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-023 — «Адресность»

> **Status:** Approved
> **Created:** 2026-06-23
> **Feature:** BOB-023

---

## Беады (создаются ПОСЛЕ утверждения PLAN)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (пламбинг) | `MessageReceived` += `reply_to_sender_id` + `mentions_bob`; multibot извлекает из aiogram Message (`reply_to_message.from_user.id`, `entities` mention) против id/username бота Боба (`BotRegistry`/`get_me`); прокинуть identity в роутер. Тесты на фейк-aiogram. | — |
| `.2` | **dev** (детектор + политика + SILENT) | `domain/personality/addressivity.py` (`Addressivity` + чистая `classify_addressivity`) + политика в `handle_message` (к Бобу→ответ; к другому→SILENT, интерес втягивает (высокий порог); ambient→молча/лайк/втягивает легче) + новый исход **SILENT**; композиция с .2a/REACT_ONLY/гость. Конфиг `addressivity.*`. | `.1` |
| `.3` | **test** | ≥80% + US-1..3 + guardrails (прямое→всегда ответ; 1:1 owner↔Bob ambient→вступает; чужой 1:1→SILENT но интерес втягивает редко; гост-инвариант цел) + регрессии. Через `.venv/bin/pytest`. | `.1,.2` |
| `.4` | **review** | Прямое обращение не теряется; не перехватывает чужой диалог; SILENT корректен; гост-инвариант BOB-019 цел; без регрессий. Read-only. | `.3` |
| `.5` | **tech-writer** | `architecture.md` (рус): пламбинг, Addressivity, политика+SILENT, BobNet-основа. Gate. | `.4` |

## Волны (последовательно на одной ветке)

```
.1 (пламбинг) → .2 (детектор+политика+SILENT) → .3 test → .4 review → .5 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-023`, один PR.
- Тесты — `.venv/bin/pytest` (uv run висит), один прогон за раз.

## Критерии готовности

- [ ] Адресность работает: к Бобу→ответ; к другому→SILENT (интерес втягивает редко); ambient→молча/лайк/
      редкий ответ; `SILENT`-исход.
- [ ] Прямое обращение всегда отвечается; 1:1 с другом не перехватывает; гост-инвариант BOB-019 цел.
- [ ] Реактив/проактив/память/личность/тиринг не сломаны; cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
