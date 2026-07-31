> **Status:** Approved
> **Type:** feature
> **Created:** 2026-07-31
> **Issue:** BOB-072

# CONTEXT — BOB-072 Holistic stream-read

## Состояние
- **Фаза:** реализация. **Ветка:** `features/BOB-072-stream-read` (от main 4f86770+BOB-071).
- **Домены:** `conversation/` (batch-read контракт + политика), `application/runtime/intake/`
  (`_handle_batch` врезка + коалесинг), `presence/` (stale-coalesce), `application/router` (rate-cap).

## Ключевые решения (утв. owner)
1. **Прямое обращение = гарантия (INV-1); ambient = семантика.** Focal отделяется ДО batch-read.
2. **Никакой скриптованности:** выбор «на что реагировать» из ambient-пачки — LLM-суждение над всей
   пачкой (`BatchRoomReader`), НЕ `plan_series_actions` формула.
3. **Персист + floor для ВСЕХ** сообщений пачки, включая пропущенные (тред цел — урок BOB-071).
4. **Живость > экономия:** read не удешевляется; коалесинг = один холистический read вместо N.
5. **За флагом** `presence.stream_read` (OFF by default → прод byte-identical до активации).

## Опорные точки (из разведки)
- `application/runtime/intake/dispatcher.py:158 _handle_batch` — ТОЧКА врезки (сейчас top-k+loop).
- `application/runtime/intake/inbox.py:75 drain_batch` + `decisions.should_debounce` — коалесинг (готов).
- `runtime/composition.py:857 intake_debounce_ms` (=0 → включить).
- `conversation/room_reading.py` (RoomReading value-типы), `room_reading_wire.py:78` (one-msg prompt →
  batch), `room_verdict.py:87 decide_from_reading` (→ decide_batch).
- `presence/series_salience.py plan_series_actions` — скриптованный top-k (уходит/сводится).
- `presence/staleness.py decide_staleness` — stale-ядро (→ queue-coalesce).
- `application/router/llm_router.py` — Tier-1 путь (rate-cap).
- Персист/floor: `turn_gate.py` `_advance_silent`/`_react_turn` (BOB-071 Seam B).

## Стандарты (CLAUDE.md §0.1/§0.2)
Python 3.12 asyncio; DDD/Clean; TDD; BDD `.feature` (behavior-bearing — обязательно тут); mutation ≥85%
на чистых ядрах (`decide_batch`, stale-coalesce, focus/ambient split policy); ruff; mypy --strict;
beadloom reindex --full + lint --strict + ci.

## DoD
pytest · mypy --strict (src+tests) · ruff · beadloom ci GREEN · mutation ≥85% чистых политик ·
BDD-сценарии (пачка→семантический выбор; INV-1 в пачке; кросс-ток молчит но помнит; протухшее не
отвечается) · живой смоук batch-read против реального Qwen (пачка → осмысленный per-message выбор).
Флаг OFF = прод byte-identical.
