<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062.8 — «Закрытие каркаса» (ФИНАЛ эпика)

> **Status:** In Progress
> **Updated:** 2026-07-28
> **Branch:** `features/BOB-062.8` · **Родитель:** `bob-8r4.8` (эпик `bob-8r4`)

---

## Беады .8

| Беад | Роль | Статус |
|------|------|--------|
| `bob-8r4.8.1` | dev — ports-шим #18 + kernel→src/bob/kernel/ + удалить domain/ | ○ ready |
| `bob-8r4.8.2` | dev — no-monster флип→error + хардинг генератора | ● blocked (.1) |
| `bob-8r4.8.3` | test — нет domain/ports + no-monster + full-reindex + mypy | ● blocked (.1,.2) |
| `bob-8r4.8.4` | review — шим удалён + kernel shared + зубы | ● blocked (.3) |
| `bob-8r4.8.5` | tech-writer — architecture #4 + getting-started #5 + doc-gen #3 + закрыть эпик | ● blocked (.4) |

## 🔴 Ключевое решение (kernel home — утв. owner)
`src/bob/kernel/ports.py` — shared kernel (7 контрактов: Clock/EventBus/LLMProvider/…). НЕ runtime
(no-runtime-root). Удалить вырожденную `src/bob/domain/` целиком — последняя layer-first папка исчезает.

## Заметки
- #18: 109 файлов, 120 импортов на канон (44 non-kernel + 7 kernel). Удалить test_ports_reexport.
- no-monster флип: безопасен (0 warnings; gateway.py #25 = component вне охвата).
- Хардинг: char-class [!au]* пропускает addressivity/absence/urge → explicit-path.
- #4 architecture 4318→nav-shell (sync-check re-mark 203 пары). #5 getting-started. #3 doc-gen 8 узлов.
- 🔴 DoD: reindex --full + mypy ПОЛНЫЙ (уроки #142/.6b).
- После .8 — ЭПИК BOB-062 ЗАКРЫТ (остаётся бэклог #25-28 clean-code, #31/#32 нагрузка).

## Прогресс
- 2026-07-28: финальный срез; BRIEF Approved (kernel→src/bob/kernel/); 5 роль-беадов; ветка. Старт Волны 0.
