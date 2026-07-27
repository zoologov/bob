<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062.4 — «Срез capabilities + генератор правил»

> **Status:** In Progress
> **Updated:** 2026-07-23
> **Branch:** `features/BOB-062.4` · **Родитель:** `bob-8r4.4` (эпик `bob-8r4`)

---

## Беады (последовательно, 6 — на 1 больше: генератор)

| Беад | Роль | Статус |
|------|------|--------|
| `bob-8r4.4.1` | dev — генератор + explicit-path + дыра (каркас) | ○ ready (Волна 0) |
| `bob-8r4.4.2` | dev — переезд capabilities (~27ф) | ● blocked (.1) |
| `bob-8r4.4.3` | dev — правила capabilities (перезапуск генератора) | ● blocked (.2) |
| `bob-8r4.4.4` | test — инварианты + c/c изоляция | ● blocked (.3) |
| `bob-8r4.4.5` | review — переезд + генератор + вердикт | ● blocked (.4) |
| `bob-8r4.4.6` | tech-writer — SPEC/DOC + #16 + Gate | ● blocked (.5) |

Критпуть: `.1 → .2 → .3 → .4 → .5 → .6`.

## Два этапа

- **A (.1):** каркас правил — `scripts/gen_boundary_rules.py` (explicit-path, marker, `--check`) +
  конвертация char-class coding/memory/proactivity + `internals-no-adapters` всем. Чинит c/c-коллизию
  и дыру test .3. ДО capabilities.
- **B (.2–.6):** переезд capabilities (~27ф, крупнейший).

## Заметки

- 🔴 c/c коллизия (capabilities/coding) — центр среза; explicit-path обязателен.
- progress_announcer целиком; InterimLineGenerator → кандидат .6.
- Новые импортёры: privileged_fulfiller, llm/factory→capabilities (RUNTIME legalized).
- Инварианты: SSRF/PrivacyGuard/shared-sink CollectingDiagramSink/tool-loop/announce.
- Дизайн генератора + движок: forbid_import одиночный glob (O(N²)); паттерн internals-no-adapters `[!au]*`.

## Прогресс

- 2026-07-23: BRIEF Approved; 6 роль-беадов; ветка `features/BOB-062.4`. Старт Волны 0 (.1 генератор).
