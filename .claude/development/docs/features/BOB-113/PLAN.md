<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-113

> **Status:** Approved
> **Created:** 2026-10-21
> **RFC:** [RFC.md](RFC.md) (Approved) · **CONTEXT:** [CONTEXT.md](CONTEXT.md)

---

## Срезы и беады

| Беада | Роль | Что | Зависит |
|---|---|---|---|
| `.1` | dev | **RFC C — kernel.** `application/runtime/events.py` → `kernel/events.py` (целиком, все импорт-сайты src+tests); `Recalled` → `kernel/episode_types.py`; `EpisodeReader`, `MemoryRecall`, `ReplyGateway`, `BobUserIdSource`, `ToolDefinition`/`ToolCall`/`ToolCallResult`/`ToolCallingProvider` → `kernel/ports.py`; `RuleModulators` → `kernel/modulators.py`. Старые объявления удаляются, ре-экспортов нет. Докстринги/README с путями. | — |
| `.2` | dev | **RFC A + B — владельцам.** `PersonalityState` → `personality/state.py`; `EngagementState` → `conversation/engagement.py`; 5 social-читателей → `social/ports.py`; `CurrentFascinationReader` → `personality/ports.py`. `handle_message.py` импортирует вниз; потребители — по новым путям. | `.1` |
| `.3` | dev | **RFC E — ISP.** `VerifySearch` + `HasAnswer` Protocol'ы в `conversation/ports.py`; `verify_step.py` и проводка (`runtime/wiring/*`) — на них; `capabilities.ports.WebSearchProvider` остаётся для своих потребителей. | `.1` |
| `.4` | dev | **RFC D — Shared Kernel социального словаря.** `Interlocutor`/`InterlocutorKind`/`Trust`/`Gender`(Enum) → `kernel/interlocutor.py`; `Relationship` → `kernel/relationship.py`; `RosterMember` → `kernel/roster.py`; `SulkState` → `kernel/sulk.py`. Поведение остаётся в `social/*`; все импорт-сайты (src 54 / tests 61) — на kernel. `services.yml`: summary `kernel`, `social`, `memory`, `capabilities`, `proactivity`, `runtime-app`. **После этой волны `lint --strict` = 0 на `error`.** | `.2`, `.3` |
| `.5` | test | **Гарды класса.** В `tests/test_no_runtime_import_cycles.py`: (а) ни один `TYPE_CHECKING`-импорт не направлен вверх по объявленному порядку (порядок — константа, выведенная из runtime-рёбер; тест называет ребро-нарушитель); (б) `bob.kernel` импортируется в изоляции и не тянет ни одного `bob.*`-модуля. Саботаж обоих — имена покрасневших в отчёте. Сверка diff'а тестов: только пути/патчи, ни одного ослабленного ассерта (список файлов в беаде). | `.4` |
| `.6` | review | Роль `review`: по каждому из 22 имён — решение RFC реализовано ровно так (таблица «имя → новый путь → импортеры»); нет ре-экспортов/шимов; `kernel` без первопартийных импортов; поведение не изменилось (diff по функциям пуст); гейты на финальном дереве **релизным 9.0.0 и чистым индексом**, числа до/после. | `.5` |
| `.7` | tech-writer | `docs/domains/kernel` (или где живёт README kernel) — новые дома контрактов; README `social`/`memory`/`capabilities`/`proactivity`/`conversation`/`personality` — переехавшие имена; `architecture.md`; ROADMAP (BOB-113 отгружен, BOB-112 разблокирован); `sync-check`/`docs audit` 0. | `.6` |

## Волны

```
W1: .1                      (kernel — фундамент: всё остальное импортирует из него)
W2: .2 ‖ .3                 (параллельно: .2 правит handle_message + personality/social/conversation; .3 — conversation/ports + verify_step + wiring; общий файл только runtime/wiring/* по типам параметров → .3 правит ТОЛЬКО wiring, где VerifySearch; .2 wiring не трогает)
W3: .4                      (социальный словарь — самый широкий diff; lint → 0)
W4: .5 → .6 → .7            (гарды, ревью, доки)
```

🔴 Правило параллельной волны W2 (§0.3 п.9): `.2` и `.3` не делят ни одного файла. Если `.2`
понадобится `runtime/wiring/*` — координатор сериализует (сначала `.3`, потом `.2`).

## Гейт каждой волны

Полный `pytest` + `ruff` + `mypy src/ tests/` + `lint --strict` релизным 9.0.0 на чистом
индексе + `test_no_runtime_import_cycles.py`. В ACTIVE после волны — числа: рёбер / type-only /
cycle-строк / пар. Волна не коммитится красной.

## Критический путь

`.1 → .2 → .4 → .5 → .6 → .7` · после `.7`: PR `features/BOB-113 → features/BOB-112`,
мёрж, закрытие BOB-112 `.2`, продолжение BOB-112 `.3`–`.5`.

## Что считается готовым

Критерии приёмки PRD, все восемь, с числами в ACTIVE и беаде-родителе.
