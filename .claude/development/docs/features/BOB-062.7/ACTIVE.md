<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062.7 — «application+runtime: app.py→runtime + kernel-split»

> **Status:** In Progress — .7a
> **Updated:** 2026-07-28
> **Branch:** `features/BOB-062.7` (для .7a) · **Родитель:** `bob-8r4.7` (эпик `bob-8r4`)

---

## Под-эпик: .7a (текущий) → .7b

- **.7a** — app.py (2819) → `src/bob/runtime/` + инлайн-адаптеры по домам + shim. **Текущий PR.**
- **.7b** — kernel-split (SqliteMemoryRepo → connection-kernel ↔ MemoryRepo). После .7a.

## Беады .7a

| Беад | Роль | Статус |
|------|------|--------|
| `bob-8r4.7.1` | dev — app.py→runtime + адаптеры + shim | ○ ready (Волна 0) |
| `bob-8r4.7.2` | dev — правила (расширить no-composition-root на runtime) | ● blocked (.1) |
| `bob-8r4.7.3` | test — инварианты + mypy ПОЛНЫЙ + launcher | ● blocked (.1,.2) |
| `bob-8r4.7.4` | review — composition-root + инварианты + shim | ● blocked (.3) |
| `bob-8r4.7.5` | tech-writer — SPEC runtime + #10/#17 + Gate | ● blocked (.4) |

## 🔴 Чек-лист инвариантов (разведка — точные строки)

- `_REPO_ROOT` parents[2]→**parents[3]** + unit-тест (промах = DENY интроспекции).
- boot-order: multibot→{sulk/si/engine/pursuit/handle_message} дословно.
- shared-instance: diagram_sink (кортеж из _build_registry), notable_reaction, resolved_bots — один инстанс.
- feature-flags off→None→inert (все).
- Коллизия: `bob.application.runtime` (async, остаётся) vs новый `bob.runtime` (composition).
- launcher `./bob` (LAUNCH + pgrep) через shim; monkeypatch redirect.
- 7 правил `*-no-composition-root` → расширить на `bob/runtime`.
- 🔴 mypy ПОЛНЫЙ (src+tests) — урок .6b.

## Прогресс

- 2026-07-28: под-эпик .7a+.7b; BRIEF Approved (.7a); 5 роль-беадов; ветка `features/BOB-062.7`. Старт Волны 0.
