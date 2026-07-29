<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-066 — «Человеческое групповое присутствие»

> **Status:** In Progress
> **Updated:** 2026-07-29
> **Эпик-беад:** `bob-vol` · **Ветка:** `features/BOB-066`

---

## Беады (эпик `bob-vol`)

| Срез | Беад | Тема | Статус |
|------|------|------|--------|
| **0** | `bob-vol.1` | Инструментарий качества (pytest-bdd + mutmut + scaffold) | ○ ready (роли .1.1–.1.4) |
| 1.1 | `bob-vol.2` | Reply-to на выходе | ● blocked (S0) |
| 1.2 | `bob-vol.3` | Floor-по-говорящему | ● blocked (S0) |
| 2.1 | `bob-vol.4` | Intake-развязка + TurnScope | ● blocked (S0) |
| 2.2 | `bob-vol.5` | Рефлексивный read-the-room + split + INV-1 + web-лаз | ● blocked (S0,1.1,1.2,2.1) |
| 2.3 | `bob-vol.6` | Ритм-слой presence/ + доля эфира | ● blocked (S0,2.1) |
| 2.4 | `bob-vol.7` | RoomMood-в-тоне + салиенс/бюджет | ● blocked (2.2,2.3) |
| 2.5 | `bob-vol.8` | Per-person обида/охлаждение | ● blocked (S0) |
| 2.6 | `bob-vol.9` | Такт разглашения + кредит доверия | ● blocked (S0) |
| 3.1 | `bob-vol.10` | Staleness/merge-gate | ● blocked (2.1,2.3) |
| 3.2 | `bob-vol.11` | Backlog catch-up + бэкпрешер | ● blocked (2.1,2.2,3.1) |

**Критический путь:** `S0 → 1.2 → 2.1 → 2.2 → 2.4 → 3.2`.

## Срез 0 — роль-беады (текущий фокус)

| Беад | Роль | Статус |
|------|------|--------|
| `bob-vol.1.1` | dev — harness (pytest-bdd+mutmut+scaffold) | ○ ready |
| `bob-vol.1.2` | test — harness зелёный + порог | ● blocked (.1.1) |
| `bob-vol.1.3` | review — метод BDD+mutation | ● blocked (.1.2) |
| `bob-vol.1.4` | tech-writer — dev-доки | ● blocked (.1.3) |

## Пирамида качества (CONTEXT §Парадигмы)

BDD acceptance (pytest-bdd+Gherkin) · Mutation (mutmut, прицельно domain, ≥85%) · TDD unit · DDD +
Cohesion. 🔴 DoD: full-reindex + full-mypy + `beadloom ci`.

## Прогресс
- 2026-07-29: PRD/RFC/CONTEXT/PLAN Approved; методология DDD/TDD/BDD/Cohesion/Mutation зафиксирована
  стоячей (CLAUDE.md §0.2 + 4 роль-агента); эпик `bob-vol` + 11 срезов + Срез-0 роли созданы, DAG
  связан. Старт Среза 0.
- 2026-07-29: `bob-vol.1.1` dev — harness готов и ЗЕЛЁН по всем своим гейтам (pytest 3318, ruff,
  mypy full, reindex --full + lint --strict 0, sync-check/doctor). Добавлены pytest-bdd+mutmut;
  tests/acceptance/{features,steps}/ + fake_gateway (FakeGateway граница + run_turn) + conftest;
  первый .feature `direct_address` GREEN; [tool.mutmut] прицельно на чистый domain; scripts/mutation.sh
  + dev-docs/MUTATION.md. Baseline sulk = 80% (56/70) → цель test-волны .1.2.
  🔴 БЛОКЕР (НЕ этот беад): `beadloom ci` красен ТОЛЬКО на config-check — 4 дрейф-адаптера
  `.claude/agents/*.md` из epic-setup коммита 94244e3 (методология BDD/Mutation вписана руками, а
  composer beadloom её не знает; `--fix` СТИРАЕТ методологию). Решение — за координатором (принять
  дрейф ИЛИ upstream quality-overlay в beadloom). Роль-адаптеры оставлены как задумано эпиком.
- 2026-07-29: **Срез 0 + Фаза 1 ЗАВЕРШЕНЫ и СМЕРЖЕНЫ в main (PR #89, 3b440de).** Блокер config-check
  РЕШЁН: методология-якорь = CLAUDE.md §0.2, адаптеры в канон, enforcement через CONTEXT + инъекцию
  в промпты; BDL-UX #139 (обезличенно). Фаза 1: 1.1 reply-to (OutgoingTarget, mutation 100%) + 1.2
  floor-по-говорящему (participants legacy-safe, mutation 103/103). pytest 3366, mypy full, beadloom
  ci green. Методом: dev→test→review→tw по слайсу, per-фаза PR (merge-commit).
  🔴 УРОКИ: параллельные dev на общем worktree → впредь ПОСЛЕДОВАТЕЛЬНО; `bd merge-slot` баглив (обход:
  git add по путям).
- 2026-07-29: **Старт Фазы 2 (сердце).** Слайс 2.1 intake-развязка + TurnScope (bob-vol.4.1..4.4) —
  критический/тяжёлый, веду сфокусированно. Далее 2.2 рефлексивный read+INV-1 → 2.4 → 2.5/2.6.
- 2026-07-29: **`bob-vol.4.1` dev — intake-развязка ОТГРУЖЕНА** (features/BOB-066 @ f29d7b1).
  application/runtime/intake/{decisions,scope,inbox,dispatcher,focus}: подписчик MESSAGE_RECEIVED →
  ChatDispatcher.submit (не-блок), per-chat воркер сериализует чат (INV-5), TurnScope rng-изоляция
  (INV-4), фокус минует debounce (INV-1/10). rng проброшен во все seeded-draw коллабораторы
  (plan/engagement/verbosity/addressivity/gate/compose/guard) через optional-param fallback →
  поведение single-turn идентично. Application.intake_dispatcher + shutdown-дренаж; poll/gateway/
  event_bus не тронуты. 34 unit + BDD intake_burst.feature + mutation 4/4 (100%) на decisions.
  pytest 3399, mypy full 0, ruff 0, reindex --full + lint --strict 0, doctor PASS. 🔴 beadloom ci:
  единственный красный = 216 stale doc (signatures changed) → tech-writer-волна (sync-update +
  setup-rules --refresh). Существующие e2e/acceptance обновлены (publish→enqueue + wait_for_idle).
  Далее: 4.2 test (гонки/сериализация/turn-scope) → 4.3 review → 4.4 tech-writer (закрывает Gate).
- 2026-07-29: **`bob-vol.8.1` dev — per-person обида/охлаждение ОТГРУЖЕНА** (features/BOB-066 @ 99afd8f).
  Обобщение owner-only sulk → per-(persona, sender): `person_sulk` таблица (PK persona+sender) +
  `PersonSulkStore` порт (load/save/active_sulks) + `SqlitePersonSulkStore` (UPSERT + backfill_owner
  идемпотентно/existence-guarded, не воскрешает). `SulkTracker` per-person: `current_for(sender_id)`/
  `observe(sender_id,person_warmth)`/`active_targets`/`recover`-iterate-active/`current_active`(owner-
  veto) + `GroupSilentAnnouncer` (тихо в группе, `observe(announcer=)`-override). Снят owner-gate в
  `social_context`; 🔴 addressed cold — `sulk_directive` только для текущего собеседника
  (`current_for(interlocutor.sender_id)`). Domain `sulk.py`: `owner_warmth`→`person_warmth` (логика
  та же). 🔴 OWNER byte-identical (owner=единственный live sender→те же пороги/decay/announce; backfill
  хранит mid-обиду). Guest-sulk + silent-group ЛАТЕНТНЫ (группы не live). INV-6 (порог+sustain+гарант.
  time-decay, анти-Exodus, directed≠casual, healthy resets). 19 domain + 15 tracker + 8 adapter unit,
  handle_message guest-тест инвертирован (теперь кормит per-person), BDD `person_sulk.feature` (адресный
  холод/бытовой мат/decay-exit) 4 сценария, mutation `bob.social.sulk` 146/147 = 99.3% (1 equivalent
  triaged: mutmut_29 drops `announced=False`, дефолт уже False). pytest 3645, mypy full 0, ruff 0,
  reindex --full + lint --strict 0 (нет цикла personality↔social — директивы argument-shaped), doctor
  PASS. 🔴 beadloom ci красный = stale doc (social README/architecture) → tech-writer-волна. Далее:
  8.2 test (инварианты) → 8.3 review → 8.4 tech-writer (закрывает Gate).
