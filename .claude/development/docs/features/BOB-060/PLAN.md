<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-060 — «Голос Боба при поиске»

> **Status:** Approved
> **Created:** 2026-07-01
> **CONTEXT:** `./CONTEXT.md`

---

## Беады (DAG)

Родитель: **`bob-060`** [feature] — «[BOB-060] Голос Боба при поиске».

| Беад | Роль | Описание | Зависит от |
|------|------|----------|-----------|
| `.1` | dev | **Вырезать зашитое + унифицировать на живой генератор.** `progress_announcer.py`: удалить `WEB_SEARCH_PROGRESS_PHRASES`/`DEFAULT_PROGRESS_PHRASES`/`phrases`/seeded-fallback; `GatewayProgressAnnouncer` ctor (`chat_id`/`gateway`/`line_generator`/`sender_name`; без rng/phrases); единый `_announce_live(topic)` (генератор→strip→пусто/сбой→**тишина**); `announce_verify(topic)`+`announce(name,query)` через него. `tool_loop.py`: `announce(call.name, call.arguments)` (передать query). `handle_message.py`: оба анонсера с `line_generator`+`sender_name`. | — |
| `.2` | dev | **Register-nudge: находка/хедж голосом Боба (US-3).** grounded/hedge-заметка (BOB-057) + манифест-преамбула просят подать поиск как «Боб сходил посмотрел», не «отчёт агента»; GUPPI-нотис по канону, но живой. Мягкий промпт-nudge, без переписывания синтеза. При нужде чуть обобщить промпт `interim_line`. | `.1` |
| `.3` | test | **Тесты.** 🔴 нет `WEB_SEARCH_PROGRESS_PHRASES` в коде (grep-инвариант); оба пути (`announce`/`announce_verify`) зовут генератор; сбой/пусто генератора → **тишина** (не шаблон, gateway.reply НЕ вызван зашитым); tool-loop передаёт query как topic; декоративность (сбой не ломает ход); register-nudge (семантически: находка/хедж в голосе Боба, не отчёт); латентность/честный хедж BOB-053 целы. ≥80%. | `.1`,`.2` |
| `.4` | review | **Ревью (read-only).** Зашитое удалено полностью (ноль скриптованности); унификация корректна; сбой→тишина; декоративность; register-nudge не ломает синтез/честный хедж; verify-триггер/стриминг не тронуты; DDD. Findings→bd. | `.3` |
| `.5` | tech-writer | **Доки.** `docs/architecture.md` (RU): единый живой интерим (оба пути через `InterimLineGenerator`, зашитое удалено, сбой→тишина), register-nudge голоса; связь BOB-055/057/053. Beadloom Gate зелёный. | `.4` |

## Волны (coordinator)

1. **Wave 1 (dev):** `.1` → `.2` (последовательно; `.2` поверх `.1`). Ветка `features/BOB-060`, коммит per-беад.
2. **Wave 2 (test):** `.3` после dev.
3. **Wave 3 (review):** `.4` после `.3`.
4. **Wave 4 (tech-writer):** `.5` после `.4`.
5. Финал: закрыть `bob-060`, полный pytest, `beadloom ci`, PR → main, мерж, рестарт, живая проверка
   (Боб ищет → живой интерим в его голосе, не «секунду, гляну в сети…» шаблон; находка — как Боб).

## Критический путь

`.1 → .2 → .3 → .4 → .5` (линейный).

## Критерии приёмки (из PRD)

- Ни на одном пути поиска — зашитой фразы; интерим всегда живой в голосе Боба.
- `WEB_SEARCH_PROGRESS_PHRASES` удалён; сбой генерации → тишина (не шаблон).
- Находка/отказ — как Боб, не отчёт агента.
- Латентность/декоративность/честный хедж (BOB-053/055/057) целы.

## Риски

- Тишина при флапе Tier-0 → приемлемо (декоративно, осознанное решение owner).
- Register-nudge слаб/силён → семантические тесты; nudge мягкий.
- Регрессия verify-интерима (убрали fallback) → тест «сбой генератора → тишина».
