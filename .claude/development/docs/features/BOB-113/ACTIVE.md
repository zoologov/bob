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
| W2 `.2` ‖ `.3` | не замерялось | не замерялось | **14** (`.2`+`.3` вместе; изолированно от W1: `.2` 192 → 23, `.3` 192 → 144) | **6** (`memory:proactivity`, `memory:telegram`, `personality:conversation`, `personality:proactivity`, `personality:social`, `social:conversation`; `.2` снял 6 пар `*:usecases`/`usecases:*`, `.3` — `capabilities:conversation`) | exit 1 (только cycles, 0 не-cycle) |
| W3 `.4` | 81 (75 произв.) | 9 (все вниз или в kernel/слой: `capabilities→bob-domain`, `coding→bob-domain`, `coding→capabilities`, `interactive→identity`, `personality→bob-domain`, `runtime-app→bob-domain`, `social→conversation`, `telegram→memory`, `usecases→runtime-app`) | **0** | **0** | **exit 0** — 0 `:error:`-строк (38 строк вывода: 36 `rule_liveness` warn + 1 `layer_population` warn + заголовок). Кусачесть: TYPE_CHECKING-импорт `bob.social.roster` в `personality/voice.py` → exit 1, 5 cycle-пар вернулись; снят точечной правкой |

> W1 замер тем же способом на `HEAD` (2804199, src = bd7e877) и после `.1`, релизный 9.0.0, чистый
> индекс: depends_on 99 → 89 (производных 93 → 83); type-only (все импорт-строки ребра под
> `TYPE_CHECKING`, ast-подсчёт по `code_imports`) 29 → 18; `:error:`-строк lint 905 → 192
> (из них cycle 904 → 192, плюс `no-monster-modules-capabilities` 1 → 0 — 4 имени ушли из
> `capabilities/ports.py`); пар циклов 15 → 13. Строка «старт» выше (98/30) — замер BOB-112 .2
> другим способом; расхождение на 1/1 не разбиралось.

> W3 замер: релизный 9.0.0, чистый индекс, после `.4`. depends_on — `count(*) from edges where
> kind='depends_on'` (81; из них с `derived` в `extra` — 75). type-only — ребро из `depends_on`,
> все импорт-строки которого (`code_imports`, файл → узел по самому длинному `source`-префиксу)
> лежат под `if TYPE_CHECKING:` (ast) — 9; ни одно не идёт вверх по runtime-порядку вертикалей.

## Прогресс

- [x] W1 `.1` dev — RFC C (kernel) — 7988 passed / 16 skipped, ruff/mypy src+tests чисто
- [x] W2 `.2` dev — RFC A+B (владельцам) ‖ `.3` dev — RFC E (ISP) — `.2`/`.3` закрыты, таблица ниже строки 9-13 ✓ (отметка проставлена в bob-etb.8 по ревью m3)
- [x] W3 `.4` dev — RFC D (социальный словарь в kernel) — 7990 passed / 16 skipped, ruff/mypy src+tests чисто, lint --strict exit 0
- [ ] W4 `.5` test → `.6` review → `.7` tech-writer
  - [x] `.5` test — гард «type-only импорт не вверх» + сверка порядка с runtime-рёбрами; изоляция kernel уже покрыта W1 (8 модулей, discovery); саботаж обоих — красные поимённо (беада); diff тестов W1–W3: ни одного ослабленного ассерта — 7994 passed / 16 skipped
  - [x] `.8` dev-fix по ревью `.6` — M2: оба коллектора гарда читают ВСЕ формы импорта (`from bob import X`, `from bob.application import usecases`, относительные; выход за пакет → ValueError), +50 юнитов; саботаж «обмана» `from bob import social` под TYPE_CHECKING краснеет новым гардом при зелёном старом; относительный runtime-импорт краснеет двумя гардами (beadloom 9.0.0 слеп к обоим — апстрим). M1: mutmut 3.6 НЕ мутирует методы декорированных классов → у `Relationship.__post_init__`/`RuleModulators.has_any` гейта не было и до переезда; логика вынесена в функции модульного уровня, файлы в source_paths: relationship 28/28, modulators 4/4 (выпадение оси/рычага держат юниты, доказано саботажем); в scope ещё 50 таких методов — вне беады. Minor m1–m5 сделаны (+ reaction_effect 22/22 после 2 тестов). Гейты: 8074 passed / 16 skipped, ruff/mypy src+tests чисто, lint --strict exit 0 (0 error, 37 warn), sync-check 726 ok / 0 stale, audit/doctor exit 0
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
| 9 | `PersonalityState` | `handle_message.py` | `personality/state.py` | .2 | ✓ |
| 10 | `EngagementState` | `handle_message.py` | `conversation/engagement.py` | .2 | ✓ |
| 11 | `InterlocutorResolver`, `FirstImpressionReader`, `RelationshipReader`, `RosterRecaller`, `SulkReader` | `handle_message.py` | `social/ports.py` | .2 | ✓ |
| 12 | `CurrentFascinationReader` | `handle_message.py` | `personality/ports.py` | .2 | ✓ |
| 13 | `WebSearchProvider` в `verify_step` | `capabilities/ports.py` | `VerifySearch`/`HasAnswer` в `conversation/ports.py` (`answer` — read-only property: frozen `WebSearchResult` не проходит settable-атрибут, замер mypy) | .3 | ✓ |
| 14 | `Interlocutor`, `InterlocutorKind`, `Trust`, `Gender`(Enum) | `social/interlocutor.py`, `social/gender.py` | `kernel/interlocutor.py` | .4 | ✓ |
| 15 | `Relationship` | `social/relationship.py` | `kernel/relationship.py` | .4 | ✓ |
| 16 | `RosterMember` | `social/roster.py` | `kernel/roster.py` | .4 | ✓ |
| 17 | `SulkState` | `social/sulk.py` | `kernel/sulk.py` | .4 | ✓ |
