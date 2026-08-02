> **Status:** Approved
> **Type:** epic
> **Created:** 2026-08-02
> **Issue:** BOB-087

# CONTEXT — BOB-087 Человечный dev-Боб

## Суть
GUPPI-исполнитель + Боб-оператор человечный + человечная чистая память + мощный интерактив + устойчивый
Tier-0. 5 срезов A–E, срез за срезом (PR/мерж/рестарт/живая проверка человечности).

## Ключевые решения (RFC)
- A: стрим ботом GUPPI (composition.py:516 → resolved_guppi_bot), голос Боба — ботом Боба. Флаг stream_via_guppi.
- B: оператор-голос (session_voice) + дистиллятор сессии → детальные первого-лица эпизоды (не firehose).
- C: work-домен + провенанс + register-aware recall (fts/hybrid + scope-параметр); OFF→байт-в-байт.
- D: --continue/--resume + permission bypassPermissions за флагом owner-only + --add-dir за флагом.
- E: Ollama-fallback для Tier-0 в llm_router.

## Инварианты (PRD)
INV-1 канон · INV-2 детальная человечная память · INV-3 чистота (не засорять личное, провенанс) ·
INV-4 анти-яд · INV-5 безопасность (флаги/main) · INV-6 человечность (живая проверка).

## Стандарты
Python 3.12 · DDD/Clean · TDD · BDD · mutation ≥85% чистые ядра · ruff · mypy(src+tests) · beadloom · флаги OFF по умолч.

## Границы
Мульти-репо/реплики/Mini-App (T3.D–H), полная переработка личности — вне.

## Связи
[[bob-079-autobiography]] · [[bob-082-dev-dm-stream]] · [[bob-083-interactive-terminal]] · канон GUPPI (BOB-003) ·
BOB-051/066 (visibility→домен) · [[bob-076-coder-runaway]] · recall-яд BOB-074/078 · #34 [[bob-084-runner-limit-fix]].
