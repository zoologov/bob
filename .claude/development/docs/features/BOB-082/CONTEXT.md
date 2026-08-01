> **Status:** Approved
> **Type:** feature (Тир-3 T3.C, срез 1)
> **Created:** 2026-08-01
> **Issue:** BOB-082

# CONTEXT — BOB-082 Dev-канал в личке (лайв-стрим + сквозная память)

## Суть

Выделенный dev-канал в личке owner'а с односторонним лайв-стримом Claude Code CLI; группа — companion;
Боб — один разум (память сквозная); приватность по умолчанию + раскрытие по согласию owner'а. За флагом
`coder.dev_dm`.

## Ключевые решения (из RFC) — 5 потоков

1. **Сигнал канала** (chat_type/is_group) gateway→event→scope (сейчас его НЕТ).
2. **Авторизация owner-DM** (сейчас DM дропается `_passes_gate`; спец-кейс owner+DM, owner-only).
3. **Scope по МЕСТУ** (личка→owner_private, группа→public) вместо «по КТО» — чинит латентную неточность
   (owner-в-группе сейчас ошибочно private).
4. **Лайв-стрим сырых событий** в DM (progressive edit_message_text, без капа; группа — указатель).
   Порт `OwnerNotifier` transport-free → use-case не меняется, только адаптер+wiring. Флаг `coder.dev_dm`.
5. **Раскрытие по согласию** (net-new): Tier-0 консент-детектор + per-turn override `filter_surfaceable(
   ..., owner_consented)` (recall-time, без мутации хранимого visibility). Консервативно.

## Инварианты (из PRD)

INV-1 сквозная память (нет chat_id-фильтра) · INV-2 scope+согласие · INV-3 односторонность (гейты целы) ·
INV-4 owner-only канал · INV-5 группа не флудится.

## Стандарты кода (CLAUDE.md §0.1)

Python 3.12+ asyncio · DDD/Clean (domain I/O-free; порты; адаптеры) · TDD · BDD `.feature` · mutation
≥85% на ядрах (scope/disclosure/render) · ruff · mypy --strict (src+tests!) · без print/breakpoint/
bare-except/мутабельных дефолтов · beadloom reindex/sync-check/lint перед коммитом.

## Границы

Без stdin/интерактива (T3.C⁺ следующим), без мульти-репо/реплик/хаба, без self-proposed, группа как есть.

## 🔴 Риски

- Scope-фикс (п.3) меняет поведение даже при флаге OFF (это корректность) — review решает контроль.
- Консент ложно триггерит → консервативный Tier-0, BDD S4/S5.
- DM недостижима (owner не нажал Start) → feasibility-смоук.
- worktree/PR-гейт (main неприкосновенен) — не трогаем.

## Связи

ROADMAP T3.C · T3.B кодер BOB-039 · [[bob-079-autobiography]] · [[bob-081-dev-introspection]] ·
BOB-051/058 (сквозная память) · BOB-066.2.6 (такт разглашения) · [[bob-076-coder-runaway]] (личка изолирует firehose).
