<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-10-21T08:49:35.850635+00:00 · coverage 100% (`persistence`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# persistence — общее ядро SQLite-соединения

Ядро персистентности: разделяемый `SqliteConnection` (open/WAL/foreign_keys/загрузка
sqlite-vec/`schema.sql`/kv/close), через который читают memory-адаптер и 13 per-module
durable-стора по инъецированному сейму `connection`. Узел `persistence` (`part_of` слоя
`bob-infrastructure`, source `src/bob/infrastructure/persistence/`) — чистый I/O: он не
несёт memory- или бизнес-логики. Сами реализации стора живут в `adapters/` своих
владеющих модулей (BOB-062.2–.7b), а не здесь.

## Спецификация

### Модули

- **connection.py** — `SqliteConnection`, разделяемое ядро соединения и схемы SQLite:
  открытие БД с WAL-журналом и `foreign_keys`, загрузка расширения sqlite-vec, применение
  `schema.sql`, key-value-хранилище (`kv_set` / `kv_get`) и корректное закрытие. Методы:
  `db_path`, `initialize`, `close`, `journal_mode`, `kv_set`, `kv_get`, `connection`.
  Здесь же живут guarded-ALTER миграции таблиц общих модулей: `CREATE TABLE IF NOT EXISTS`
  не трогает уже существующую таблицу, поэтому недостающая колонка добавляется отдельным
  `ALTER` — аддитивно, идемпотентно и без бэкфилла (`_migrate_person_relationship_gender`,
  `_migrate_first_impression_display_name`, `_migrate_first_impression_username` —
  Telegram-ник участника, BOB-090.B3; `_migrate_improvement_rule_announce` — колонки
  доставки предложения `announced` / `announce_attempts`, BOB-096).
  🔴 Отсутствие бэкфилла у последней — решение, а не упущение: дефолты читаются как «ещё
  не проговорено», поэтому предложение, записанное до фикса, прозвучит владельцу ОДИН раз
  и умолкнет навсегда. Пометить старое как уже сказанное значило бы заглушить то, чего
  владелец никогда не слышал, — миграция не утверждает историю, которой не знает.
- **__init__.py** — фасад пакета (разделяемое SQLite connection/schema-ядро).

## Инварианты

- `SqliteConnection` не несёт бизнес- или memory-логики — только I/O; доменные реализации
  стора владеют своими сущностями в `<module>/adapters/`.
- Один разделяемый инстанс инъецируется во все durable-стора через сейм `connection` —
  единый пул соединения, единая схема, единый WAL-режим.
- Схема применяется из `schema.sql`; расширение sqlite-vec загружается при инициализации.

## API

Модуль `src/bob/infrastructure/persistence/connection.py`:
- `SqliteConnection.initialize()` — открыть БД, включить WAL/foreign_keys, загрузить
  sqlite-vec, применить `schema.sql`.
- `SqliteConnection.connection` — разделяемое соединение для инъекции в стора.
- `SqliteConnection.kv_set(...)` / `.kv_get(...)` — key-value-доступ.
- `SqliteConnection.journal_mode` / `.db_path` — интроспекция; `.close()` — закрытие.

## Тестирование

Тесты: `tests/infrastructure/persistence/test_connection.py`. Per-module стора, читающие
этот сейм, покрываются собственными тестами в `tests/infrastructure/persistence/`
(например `test_goal_store.py`, `test_relationship_store.py`, `test_fascination_store.py`).

<!-- beadloom:track=src/bob/infrastructure/persistence/connection.py -->
