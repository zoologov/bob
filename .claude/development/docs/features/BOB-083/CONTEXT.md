> **Status:** Approved
> **Type:** feature (Тир-3 T3.C⁺)
> **Created:** 2026-08-01
> **Issue:** BOB-083

# CONTEXT — BOB-083 Интерактивный терминал Claude Code в личке

## Суть

Двусторонний интерактив: owner видит живой поток CLI И направляет claude в реальном времени (реплики из
лички → открытый stdin персистентного claude). За флагом `coder.interactive`. owner-only, DM-only, main
неприкосновенен.

## Ключевые решения (из RFC) — 4 потока

0. **Фундамент:** входящий owner-DM доходит до Боба (multibot сейчас дропает DM) + reply в личку (вторая
   scope-регистрация DM или chat-aware reply). Чинит и BOB-082 `/code`-из-лички.
1. **Персистентный runner:** `claude -p --input-format stream-json --output-format stream-json` с ОТКРЫТЫМ
   stdin (сейчас one-shot без stdin); держит proc-handle; feed/events/close. Чистое: `encode_user_message`.
2. **Интерактив-сессия:** новое состояние INTERACTIVE + менеджер держит живой proc + прямой kill; реюз
   `_DmLiveStreamer` (BOB-082) для вывода; worktree-изоляция+PR-гейт BOB-039 не трогаем.
3. **Интейк-режим:** реплики owner'а из лички → stdin (consume-гейт по образцу maybe_route_coding);
   `/code -i` вход + exit; явный режим (INV-5).

## Инварианты (из PRD)

INV-0 DM доходит · INV-1 двусторонность · INV-2 main неприкосновенен (worktree+PR) · INV-3 owner-only/
DM-only · INV-4 kill-switch (прямой terminate) · INV-5 честное режим-переключение.

## Стандарты кода (CLAUDE.md §0.1)

Python 3.12+ asyncio · DDD/Clean · TDD · BDD · mutation ≥85% на чистых ядрах · ruff · mypy --strict
(src+tests!) · subprocess только exec (не shell) · без print/breakpoint/bare-except/мутабельных дефолтов ·
beadloom перед коммитом.

## Границы

Без мульти-репо/реплик/хаба, без Mini-App, без авто-мержа (main через PR), без self-proposed, одна сессия.

## 🔴 Риски

Живой subprocess (зомби/утечка) → proc-handle+stop+таймаут; DM-reply в группу → тест; режим залипает →
consume строго по активной сессии; main задет → worktree+PR не трогаем; ослабление гейта → owner-only/
DM-only/флаг/security-ревью.

## Связи

ROADMAP T3.C⁺ · [[bob-082-dev-dm-stream]] (DM-канал+стрим, реюз) · кодер BOB-039 (гейты не трогаем) ·
[[bob-076-coder-runaway]] (мощное → owner-only/флаг/kill).
