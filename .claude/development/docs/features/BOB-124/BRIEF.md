<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF — BOB-124: старт Боба квадратичный — бэкфилл векторов джойнит vec0 без индекса

> **Type:** bug · **Status:** Approved
> **Created:** 2026-10-22 · **Беада:** `bob-11o` (P0)

## Проблема

После `systemctl restart bob` Боб **часами** не доходит до `AgentRuntime started`: не поллит Telegram,
не отвечает, не виден владельцу (замер 2026-10-22 на VPS после выкатки BOB-116: старт 03:33:58, в 04:21
всё ещё в инициализации памяти, процесс 95 % CPU; 0 соединений с Telegram). Это фактическая немота на
каждый рестарт — ровно тот класс, который BOB-116 только что закрыл для отказов облака.

Корень (py-spy `--native`): рабочий поток aiosqlite сидит в `vec0Column → vec0_get_partition_value_for_rowid
→ sqlite3_prepare_v2` — это `_pending_rows` в `memory/adapters/vector_store.py:141-152`:

```sql
SELECT t.id, t.content FROM episodic_log t
LEFT JOIN memory_vec v ON v.source = ? AND v.src_id = t.id
WHERE v.src_id IS NULL ORDER BY t.id
```

`memory_vec` — виртуальная таблица sqlite-vec (`vec0`); по `src_id` у неё индекса нет и быть не может,
поэтому джойн — полный скан партиции на **каждую** строку источника: `episodic_log` 27 373 ×
`memory_vec` 27 418 ≈ 750 млн обращений к `vec0Column`, каждое с `sqlite3_prepare_v2`. Код не менялся с
v1.0.0 (2026-08-18); тогда память была втрое меньше, и старт занимал ~2 минуты (18:21 → 18:23). Рост —
квадратичный, то есть со временем только хуже. Доп. фактор: под конкуренцией за CPU (замер Ollama на тех
же 4 vCPU) старт вообще не завершился за 10 минут.

## Решение

Структурно, без флагов и «пропусков»:

1. **Анти-джойн без vec0.** `_pending_rows` получает множество уже встроенных id одним линейным запросом
   `SELECT src_id FROM memory_vec WHERE source = ?` (27 k целых — копейки) и выбирает строки источника,
   которых в нём нет: либо фильтр в Python по `SELECT id, content FROM <table> ORDER BY id`, либо
   временная обычная таблица `_vec_done(src_id INTEGER PRIMARY KEY)` + `NOT EXISTS` — что быстрее по замеру,
   то и берём (ожидание: секунды на 27 k). Тот же приём для `_has_vector` (`:196`), если он на горячем пути.
2. **Замер до/после на копии прод-БД** (134 МБ, read-only копия `bob.db` → scratch): время
   `backfill()` при 0 недостающих векторов; цель — ≤ 5 с против часов. Числа — в ACTIVE и в беаду.
3. **Лог прогресса старта:** `SqliteMemoryRepo` пишет одну строку «бэкфилл: источник, всего/недостающих,
   N с» — чтобы следующий долгий старт был виден в журнале, а не угадывался по py-spy.
4. **Регресс-тест на масштаб:** synthetic БД с 30 000 эпизодов и полным `memory_vec` — `backfill()`
   укладывается в бюджет (например ≤ 3 с на CI) — тест на настоящем sqlite + sqlite-vec (не на фейке,
   П.0.3 п.4); саботаж: вернуть старый LEFT JOIN — тест краснеет по таймауту/бюджету с именем.
5. Issues: новая запись **#73** (эта находка, с числами), ссылка из #64 (смоук §10.1 отложен из-за неё).

## Axes

> **Derived by:** `beadloom impact src/bob/memory/adapters/vector_store.py` over `src/bob` (9.0.0, 2026-10-22)
> **Seed:** `_render_templates` (`serialises-yaml`), rule `reaches-an-effect-sink`
> **Unresolved:** 3 name-defined-more-than-once, 3 unresolved-terminator-name; `Owns unread: none` везде

| Axis | Node | Sites | Owns unread | In scope | Why |
|---|---|---|---|---|---|
| co-writers | `social` | 1 — `social/usecases/run_genesis.py:139` | none | no | пишет YAML genesis; к бэкфиллу не относится |
| callers | `memory` | 5 — `memory/adapters/ollama_embedder.py:85` | none | yes | единственный узел работы: `vector_store.py` (`_pending_rows`, `_has_vector`), `sqlite_memory_repo.py` (строка лога прогресса) |
| callers | `capabilities` | 2 — `capabilities/adapters/web/http_url_reader.py:323` | none | no | не вызывает бэкфилл |
| callers | `conversation` | 1 — `conversation/brevity.py:188` | none | no | то же |
| callers | `llm` | 2 — `infrastructure/llm/fallback_provider.py:224` | none | no | то же |
| callers | `router` | 1 — `application/router/reply_tier_selector.py:81` | none | no | то же |
| callers | `usecases` | 1 — `application/usecases/essential_runner.py:70` | none | no | то же |
| branches | `memory` | `backfill` 1/1, `_backfill_source` 1/0, `_pending_rows` 1/1, `_has_vector` 1/1, `_embed_batch` 1/1 | none | yes | меняемые ветки |
| branches | прочие | `router`/`usecases`/`capabilities`/`conversation` — from a caller's seat | none | no | не меняются |

Оси называют один узел в scope → маршрут `bug`, упрощённый поток.

## Что НЕ входит

- Ленивый/фоновый бэкфилл, инкрементальная инициализация памяти — отдельная работа, если после фикса старт
  всё ещё > 1 мин по замеру.
- Рестарт-нотис «только после готовности» — отдельно (BOB-094 семантика), здесь только лог прогресса.
- Смоук BOB-116 §10.1/§10.2 — после выкатки этого фикса (ACTIVE BOB-116).

## Acceptance

- [ ] `backfill()` на копии прод-БД (27 k строк, 0 недостающих) — ≤ 5 с (число — в ACTIVE); старт Боба на
      VPS после выкатки — `AgentRuntime started` ≤ 2 мин от `Bob GUPPI starting`
- [ ] регресс-тест на масштаб на настоящем sqlite-vec; саботаж старым JOIN — красный с именем
- [ ] строка прогресса бэкфилла в логе старта
- [ ] существующие тесты vector_store/memory зелёные; `beadloom ci` на чистом индексе 9.0.0 PASS
- [ ] Issues #73; PR → `main`, мёрж владельцем, выкатка `workflow_dispatch ref=main`
