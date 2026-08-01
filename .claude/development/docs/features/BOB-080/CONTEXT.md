> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-080

# CONTEXT — BOB-080 Ростер комнаты

## Суть

Боб держит соц-ростер знакомых и припоминает состав по социальному поводу (называет недавних сам, без
подсказки имён), отделяя новичков (по времени) от старожилов. За флагом `social.roster`.

## Ключевые решения (из RFC)

- **DATA:** первый recency-запрос `FirstImpressionStore.recent(limit)` (`ORDER BY first_seen_at DESC`);
  guarded ALTER колонка `display_name` (заполняется в `note_first_contact`), legacy-имя — парс из note.
- **Ядро** `social/roster.py` (pure): `RosterMember`, `is_newcomer(first_seen, now, newcomer_days)`,
  `build_roster(...)` (исключить владельца, порядок DESC, limit, флаг новичка) — mutation ≥85%.
- **Usecase** `RosterRecall`: ambient-окно (ростер только если есть свежий новичок) + приватность
  (только viewer OWNER/KNOWN) + best-effort; через `SocialContext` в `handle_message` → промпт.
- **READ:** мульти-персонная `roster_directive` в voice.py (компактно, «называй по поводу, не притягивай»)
  → `voice_composer.py:408` directives.
- **Флаг** `social.roster` (default OFF → ON в running-config), `newcomer_days`=7, `limit`~6.
- 🔴 surfacing = **ambient-окно**, НЕ keyword-детектор (north star: не скриптовость).

## Инварианты (из PRD)

INV-1 реальные встречи · INV-2 припоминание без имён (не по FTS) · INV-3 новизна по времени ·
INV-4 точечность (не флуд).

## Стандарты кода (CLAUDE.md §0.1)

Python 3.12+ asyncio · DDD + Clean Architecture (domain I/O-free; порты; адаптеры на краю) · TDD ·
BDD `.feature` (`tests/acceptance/`) · mutation ≥85% на ядре · ruff · mypy --strict (без `Any`/`ignore`
без причины) · без `print`/`breakpoint`/bare-except/мутабельных дефолтов · beadloom reindex/sync-check/
lint перед коммитом.

## Границы

Без live-членства Telegram, без переписи engagement BOB-078, без authz, без проактивного «первым к новичку».

## Связи

[[bob-079-autobiography]] (то же обсуждение, Факт 1) · [[bob-social-identity-strangers]] (BOB-019) ·
[[bob-078-dialogue-quality]] (engagement/новичок, best-effort) · [[bob-072-stream-read]] (точечность/флаг).
