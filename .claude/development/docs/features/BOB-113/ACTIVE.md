<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE — BOB-113

> **Беада:** `bob-etb` (P1, feature) · **Ветка:** `features/BOB-113` (от `features/BOB-112` `bd7e877`)
> **Спека:** [PRD](PRD.md) · [RFC](RFC.md) · [CONTEXT](CONTEXT.md) · [PLAN](PLAN.md) · **Обновлено:** 2026-10-21

---

## Фокус

Граф Боба ацикличен **по контрактам**: 22 имени переезжают туда, где их место по
runtime-порядку вертикалей; `no-dependency-cycles` возвращается в 0 на `error`. Без полумер.

## Числа гейта (релизный 9.0.0, чистый индекс)

| После волны | рёбер depends_on | type-only | cycle-строк | пар циклов | lint --strict |
|---|---|---|---|---|---|
| старт (bd7e877) | 98 | 30 | 904 | 15 | exit 1 |
| W1 `.1` | 89 (83 произв.) | 18 | 192 | 13 | exit 1 (только cycles; `no-monster-modules-capabilities` ушёл) |
| W2 `.2` ‖ `.3` | | | | | |
| W3 `.4` | | | | | **0 / exit 0** (цель) |

> W1 замер тем же способом на `HEAD` (2804199, src = bd7e877) и после `.1`, релизный 9.0.0, чистый
> индекс: depends_on 99 → 89 (производных 93 → 83); type-only (все импорт-строки ребра под
> `TYPE_CHECKING`, ast-подсчёт по `code_imports`) 29 → 18; `:error:`-строк lint 905 → 192
> (из них cycle 904 → 192, плюс `no-monster-modules-capabilities` 1 → 0 — 4 имени ушли из
> `capabilities/ports.py`); пар циклов 15 → 13. Строка «старт» выше (98/30) — замер BOB-112 .2
> другим способом; расхождение на 1/1 не разбиралось.

## Прогресс

- [x] W1 `.1` dev — RFC C (kernel) — 7988 passed / 16 skipped, ruff/mypy src+tests чисто
- [ ] W2 `.2` dev — RFC A+B (владельцам) ‖ `.3` dev — RFC E (ISP)
- [ ] W3 `.4` dev — RFC D (социальный словарь в kernel)
- [ ] W4 `.5` test → `.6` review → `.7` tech-writer
- [ ] PR `features/BOB-113 → features/BOB-112`, закрытие BOB-112 `.2`

## Таблица «имя → новый дом → сделано» (заполняется по волнам)

| # | Имя | Было | Будет | Волна | ✓ |
|---|---|---|---|---|---|
| 1 | `MessageReceived`, `BobMessageReaction` | `application/runtime/events.py` | `kernel/events.py` | .1 | ✓ |
| 2 | `Recalled` | `memory/ports.py` (объявлен там; в RFC ошибочно `memory/entities.py`) | `kernel/episode_types.py` | .1 | ✓ |
| 3 | `EpisodeReader` | `handle_message.py` | `kernel/ports.py` | .1 | ✓ |
| 4 | `MemoryRecall` | `memory/ports.py` | `kernel/ports.py` | .1 | ✓ |
| 5 | `ReplyGateway` | `handle_message.py` | `kernel/ports.py` | .1 | ✓ |
| 6 | `BobUserIdSource` | `handle_message.py` | `kernel/ports.py` | .1 | ✓ |
| 7 | `ToolDefinition`, `ToolCall`, `ToolCallResult`, `ToolCallingProvider` | `capabilities/ports.py` | `kernel/ports.py` | .1 | ✓ |
| 8 | `RuleModulators` | `proactivity/self_improvement.py` | `kernel/modulators.py` | .1 | ✓ |
| 9 | `PersonalityState` | `handle_message.py` | `personality/state.py` | .2 | |
| 10 | `EngagementState` | `handle_message.py` | `conversation/engagement.py` | .2 | |
| 11 | `InterlocutorResolver`, `FirstImpressionReader`, `RelationshipReader`, `RosterRecaller`, `SulkReader` | `handle_message.py` | `social/ports.py` | .2 | |
| 12 | `CurrentFascinationReader` | `handle_message.py` | `personality/ports.py` | .2 | |
| 13 | `WebSearchProvider` в `verify_step` | `capabilities/ports.py` | `VerifySearch`/`HasAnswer` в `conversation/ports.py` | .3 | |
| 14 | `Interlocutor`, `InterlocutorKind`, `Trust`, `Gender`(Enum) | `social/interlocutor.py`, `social/gender.py` | `kernel/interlocutor.py` | .4 | |
| 15 | `Relationship` | `social/relationship.py` | `kernel/relationship.py` | .4 | |
| 16 | `RosterMember` | `social/roster.py` | `kernel/roster.py` | .4 | |
| 17 | `SulkState` | `social/sulk.py` | `kernel/sulk.py` | .4 | |
