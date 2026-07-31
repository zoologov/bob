> **Status:** Approved
> **Type:** feature
> **Created:** 2026-07-31
> **Issue:** BOB-072

# PLAN — BOB-072 Holistic stream-read (DAG)

## Беады

```
BOB-072 [feature] — Человечное чтение потока (holistic stream-read)
├── BOB-072.1 [dev] — batch-read контракт: BatchRoomReader порт + LlmBatchRoomReader (batch-prompt/parse)
│                     + decide_batch (чистое ядро read→verdict). За флагом presence.stream_read. НЕ провязан ещё.
├── BOB-072.2 [dev] — _handle_batch врезка: focus/ambient split (focal→детерминированно INV-1;
│                     ambient→batch-read) + коалесинг (intake_debounce_ms>0) + применение с персист+floor
│                     ВСЕХ (BOB-071 Seam B). Заменяет plan_series_actions top-k. deps .1
├── BOB-072.3 [dev] — queue-level stale-coalesce (superseded ambient не отвечается; focal не дропается) +
│                     Tier-1 rate-cap semaphore. deps .2
├── BOB-072.4 [test] — unit (decide_batch, split, stale, rate-cap) + BDD (пачка→семант.выбор; INV-1 в
│                     пачке; кросс-ток молчит+помнит; протухшее мимо) + mutation чистых ядер +
│                     🔴 живой смоук batch-read против Qwen. deps .3
├── BOB-072.5 [review] — INV-1 цел; семантика не скрипт; персист/floor всех; детерминизм; флаг OFF byte-identical; DDD. deps .4
└── BOB-072.6 [tech-writer] — docs (conversation batch-read + intake коалесинг + presence flag). deps .5
```

## Волны
- Wave dev (последовательно, урок BOB-066): .1 контракт → .2 врезка → .3 stale+rate-cap.
- Test .4 → Review .5 (ISSUES→fix-беад) → tech-writer .6 → Gate → PR → self-merge.
- Активация: включить `presence.stream_read` + debounce в config → `./bob restart` → живой прогон
  (пачка от нескольких → Боб осмысленно выбирает) → отчёт owner.

## Критический путь
.1 → .2 → .3 → .4 → .5 → .6 → PR → merge → активация(флаг) → live-verify.

## Риски
- INV-1 в пачке: focal split ДО batch-read — focused-тест обязателен.
- Персист всех N (тред): регресс-тест BOB-071.
- Batch-prompt качество: живой смоук против Qwen (не мок) — семантический выбор реальный.
- Флаг OFF byte-identical: регресс-пин.
