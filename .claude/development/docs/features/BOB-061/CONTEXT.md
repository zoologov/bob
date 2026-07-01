<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-061 — «Анти-тик / разнообразие реплик»

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD/RFC:** `./PRD.md` · `./RFC.md`

---

## Суть (одним абзацем)

Расширить существующий анти-тик (BOB-036/043) тремя фиксами: (1) **персист closer-ов** Боба (кросс-сессионный
SQLite-стор) — чтобы «раз-в-сессию через дни» тик ловился; (2) **near-verbatim кластеризация** мотива (реюз
`similarity_threshold`) — чтобы лексические варианты считались одним мотивом; (3) **диспозиция** (BOB-033)
— мягкий тюнинг только при эмпирическом подтверждении. Провязка — **мягкий нудж к разнообразию** (не бан),
живость/связность целы.

## Ключевые решения (утв. в PRD/RFC)

1. Персист closer-ов (лёгкий SQLite-стор, кольцо) — основной фикс кросс-сессионной разреженности.
2. Near-verbatim кластеризация мотива (реюз `similarity_threshold` из `is_bob_repeat`).
3. Диспозиция (BOB-033) — мягкий тюнинг ТОЛЬКО при подтверждении драйвером; иначе пропустить.
4. Мягкий нудж («скажи по-другому»), НЕ бан — живость/связность целы.

## Что УЖЕ есть (расширяем, не дублируем)

- `domain/personality/conversation.py`: `is_phrase_tic`/`recurring_closer`/`strip_recurring_closer`,
  `RepeatThresholds` (`tic_min_words`/`tic_min_occurrences`/`tic_lookback`), `is_bob_repeat`
  (near-verbatim по `similarity_threshold`), `_notable_phrases`/`_normalise`.
- `handle_message.py`: импорт `is_phrase_tic`/`recurring_closer`/`strip_recurring_closer`/
  `recalled_without_copied_exemplars`; анти-повтор reply Боба + гашение copied-exemplars.

## Архитектура (где что менять)

- **domain `conversation.py`:** near-verbatim в phrase-tic (кластеризация closer-ов по similarity, не только
  точный `_normalise`); чистые функции детекта тика над списком closer-ов (персист + окно).
- **infrastructure:** лёгкий стор persisted-closers (SQLite, как память Боба) + порт `CloserLog`
  (append нормализованного closer после реплики; recent(k)). Кольцо ограниченного размера.
- **application `handle_message.py`:** после реплики — записать closer в персист; при сборке ответа —
  детект тика по (персист + окно) → `strip_recurring_closer` из recall + **мягкий нудж** в контекст.
- **диспозиция `disposition.py`:** точечный тюнинг застревания reappraisal/диспозиции — ТОЛЬКО если
  эмпирически подтверждён драйвером (иначе шаг минимален/пропущен).

## 🔴 Инварианты (НЕ нарушать)

- **US-4 живость (главный):** только мягкий нудж к разнообразию; Боб НЕ выхолащивается/не цензурируется/не
  рандомизируется; связность, характер, легитимные повторы-по-смыслу — целы. Тест-инвариант.
- **US-5 общий:** ловит ЛЮБОЙ повторяющийся мотив (персист + near-verbatim), БЕЗ хардкода конкретной фразы.
- **Приватность/локальность:** персист closer-ов — локально/приватно (как память Боба), ограниченный размер.
- **Не ломаем:** BOB-036/043 (расширяем, не заменяем); recall/память (BOB-011/051 — только гашение
  мимикрии); BOB-033 (мягкий тюнинг, не редизайн).
- **Декоративность:** сбой детекта/персиста → обычная реплика (ход не ломается).
- **Детерминизм:** пороги/чтения инъектируются; near-verbatim порог консервативен (не душить любую похожесть).
- **DDD:** domain (чистый детект) ← application (провязка/нудж) ← infrastructure (стор); композиция в app.py.

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio; DDD/Clean; `ruff`, `mypy --strict`; frozen+slots; TDD, покрытие ≥80%
  (`mypy src tests`). Без `print`/`breakpoint`/bare `except`/`import *`/mutable-default. Русские литералы →
  per-file-ignore RUF001/002/003. Нудж/сообщения — русский, голос Боба.

## Реюз / прецеденты

- `is_phrase_tic`/`recurring_closer`/`strip_recurring_closer`/`RepeatThresholds` (BOB-036/043) — база.
- `is_bob_repeat`/`similarity_threshold` (BOB-026) — near-verbatim, реюз для кластеризации мотива.
- `recalled_without_copied_exemplars` (гашение мимикрии) — усилить персистом.
- SQLite-память Боба (`sqlite_repo`/сторы) — образец для persisted-closers стора.
- `disposition.py`/reappraisal (BOB-033) — точка тюнинга (условно).

## Связи

BOB-036/043 (анти-тик — расширяем) · BOB-026 (near-verbatim) · BOB-032 (анти-повтор) · BOB-011/045/051
(память/recall — гашение петли) · BOB-033 (диспозиция) · [[bob-tone-dynamics]] («recall poisoning») ·
север `bob-personality-simulation-philosophy` · `bob-consciousness-markers-lens`. Последний из тройки
(после BOB-059/060).
