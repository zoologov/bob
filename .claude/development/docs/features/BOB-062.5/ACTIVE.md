<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062.5 — «Срез social → src/bob/social/»

> **Status:** In Progress
> **Updated:** 2026-07-28
> **Branch:** `features/BOB-062.5` · **Родитель:** `bob-8r4.5` (эпик `bob-8r4`)

---

## Беады (последовательно)

| Беад | Роль | Статус |
|------|------|--------|
| `bob-8r4.5.1` | dev — переезд social + разрыв цикла | ○ ready (Волна 0) |
| `bob-8r4.5.2` | dev — правила (генератор) + проверка цикла | ● blocked (.1) |
| `bob-8r4.5.3` | test — social-инварианты + изоляция | ● blocked (.1,.2) |
| `bob-8r4.5.4` | review — переезд + разрыв цикла + вердикт | ● blocked (.3) |
| `bob-8r4.5.5` | tech-writer — SPEC/DOC + #14 + Gate | ● blocked (.4) |

Критпуть: `.1 → .2 → .3 → .4 → .5`.

## Решения (утв. owner / разведка)

1. 🔴 **Вариант B (утв.):** interlocutor→social; разорвать `voice.py:37→InterlocutorKind` (voice получает
   kind значением-параметром, behavior-preserving). social владеет identity; social→personality однонапр.
2. **run_genesis → social** (чист: SoulStore+router, 0 personality).
3. **privileged_fulfiller → остаётся в application/usecases** (cross-domain оркестратор).
4. kernel (вариант C) — сторы через seam, schema остаётся.

## Заметки

- 🔴 Первый срез с разрывом цикла (code-fix, не только git mv). Аналог для .6 (personality↔conversation).
- Store-порты First/Relationship/Sulk → social; Reactor/Reflection/Fascination/Notable/Zone остаются personality.
- #31/#32 (групповая нагрузка) — риды на этой ветке, уедут в PR .5.

## Прогресс

- 2026-07-28: BRIEF Approved (вариант B); 5 роль-беадов; ветка `features/BOB-062.5`. Старт Волны 0.
