<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-062.6 — «personality + conversation + декомпозиция handle_message»

> **Status:** In Progress — .6a
> **Updated:** 2026-07-28
> **Branch:** `features/BOB-062.6a` · **Родитель:** `bob-8r4.6` (эпик `bob-8r4`)

---

## Под-эпик: .6a (текущий) → .6b

- **.6a** — два bounded-context personality/ + conversation/ + разрыв цикла. **Текущий PR.**
- **.6b** — декомпозиция handle_message #9 волнами 0→4. Свой BRIEF после мержа .6a.

## Беады .6a

| Беад | Роль | Статус |
|------|------|--------|
| `bob-8r4.6.1` | dev — разрыв цикла (Verbosity/EngagementLevel→personality, изолированно) | ○ ready (Волна 0) |
| `bob-8r4.6.2` | dev — переезд 2 vertical | ● blocked (.1) |
| `bob-8r4.6.3` | dev — правила (генератор, 2 узла) + цикл зелёный | ● blocked (.2) |
| `bob-8r4.6.4` | test — инварианты + изоляция + проба цикла | ● blocked (.1,.2,.3) |
| `bob-8r4.6.5` | review — цикл + 2 bounded-context + cohesion | ● blocked (.4) |
| `bob-8r4.6.6` | tech-writer — SPEC ×2 + #15/#16 + Gate | ● blocked (.5) |

## Ключевые решения (утв. owner — DDD/cohesion)

- **Два bounded-context** (не merged): personality=«кто Боб есть», conversation=«как ведётся ход».
- 🔴 **Разрыв цикла правильно:** conversation→personality однонаправленно. Механизм: Verbosity/
  EngagementLevel enum-определения → personality expression-вокабуляр (грани выражения характера);
  вычисляющая логика в conversation возвращает personality-VO. Тела не менять, только enum-defs+импорты.
- **Cohesion-раскол:** negotiation/reaction_judgment→personality; zone_classifier/response_judgment/
  volatility_judgment→conversation.
- **.6b отдельно** — handle_message #9 (360 тестов safety-net; не менять `_build`).

## Прогресс

- 2026-07-28: под-эпик оформлен (.6a+.6b); BRIEF Approved; 6 роль-беадов .6a; ветка `features/BOB-062.6a`.
  Старт Волны 0 (.1 изолированный разрыв цикла).

---

## .6b — декомпозиция handle_message #9 (branch `features/BOB-062.6b`)

| Беад | Волна | Статус |
|------|-------|--------|
| `bob-8r4.6.7` | 0 — free-функции → conversation-хелперы | ○ ready |
| `bob-8r4.6.8` | 1 — листовые (Diagram/Essential/Floor/Verify/PreCompose) | ● blocked |
| `bob-8r4.6.9` | 2 — средние (Addressivity/Engagement/Mood/Social/Recall) | ● blocked |
| `bob-8r4.6.10` | 🔴 3 ЯДРО — VoiceComposer + AntiRepeatGuard (callback) | ● blocked |
| `bob-8r4.6.11` | 4 — TurnGate + тонкий handle() | ● blocked |
| `bob-8r4.6.12` | test — все инварианты + _build не менялся | ● blocked |
| `bob-8r4.6.13` | review — когезия + turn-local + тонкий handle() | ● blocked |
| `bob-8r4.6.14` | tech-writer — доки + #9 + Gate | ● blocked |

🔴 Behavior-preserving method-object; НЕ менять `_build` (360 тестов); turn-local через аргументы;
seeded-RNG порядок; каждая волна — коммит, зелёные тесты между.
