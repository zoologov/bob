<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-060 — «Голос Боба при поиске»

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD:** `.claude/development/docs/features/BOB-060/PRD.md`
> **Решения (под утв.):** удалить `WEB_SEARCH_PROGRESS_PHRASES` + весь seeded-путь · `GatewayProgress
> Announcer` — ТОЛЬКО живая Tier-0-генерация · сбой/пусто → ТИШИНА (не шаблон) · tool-loop передаёт запрос
> как topic → живой контекстный интерим и на этом пути · лёгкий register-nudge находки/хеджа в голос Боба.

---

## Идея решения

Унифицировать оба пути анонса поиска на **живую генерацию** (механика BOB-057) и **вырезать зашитое**.
`GatewayProgressAnnouncer` больше не имеет seeded-набора: и tool-loop (`announce`), и verify
(`announce_verify`) генерят живую реплику в голосе Боба через `InterimLineGenerator`; при
сбое/пустом/невключённом генераторе → **тишина** (декоративно). Плюс лёгкий nudge, чтобы подача находки/
хеджа читалась как Боб, а не «отчёт агента».

## Изменения (application, `progress_announcer.py`)

**Удалить зашитое (US-2):**
- `WEB_SEARCH_PROGRESS_PHRASES`, `DEFAULT_PROGRESS_PHRASES`, параметр `phrases`, и seeded-fallback в
  `announce_verify`/`_live_verify_line`. Никаких зашитых фраз в коде.

**`GatewayProgressAnnouncer` → только живая генерация:**
- ctor: `chat_id`, `gateway`, `line_generator` (генератор — основной источник; без него → тишина),
  `sender_name` (per-turn); `rng`/`phrases` убираются.
- Единый приватный `_announce_live(topic)`: `line = await generator.generate(topic, sender_name)` →
  `strip()` → если пусто/сбой → **тишина** (лог, drop); иначе `gateway.reply`. Все ошибки глотаются
  (декоративно).
- **`announce_verify(topic)`** → `_announce_live(topic)` (topic из `verdict.topic`; sender из ctor).
- **`announce(capability_name, query)`** (tool-loop): для `web_search` → `_announce_live(topic=query)`
  (живой контекстный интерим из запроса); для прочих навыков → тишина. Сигнатура принимает контекст вызова.

**`ToolLoop` (`tool_loop.py`) передаёт запрос:**
- `announce(call.name, call.arguments)` — вытащить `query` из аргументов web_search как topic. Обёртка
  try/except (декоративность на шве) — как сейчас. Быстрые навыки → анонсер молчит.

**Провязка (`handle_message.py`):**
- Оба per-turn анонсера (tool-loop `_reply_with_tools` и verify `_send_verify_interim`) строятся с
  `line_generator` + `sender_name`. Единый путь — живой. Не провязан генератор → анонсер молча (никаких
  шаблонов).

## Register-nudge находки/хеджа (US-3)

Лёгко, без переписывания механизма поиска:
- **grounded/hedge-заметка** (BOB-057, `handle_message`): формулировка просит подать **в голосе Боба, не
  отчётом** («ответь по-своему, как Боб — без „выполнен поиск, найдено N…“»); хедж — живая оговорка.
- **capability-манифест-преамбула** (GUPPI-канон): убедиться, что подача поиска — как «Боб сходил
  посмотрел», не «агент выполнил tool». GUPPI-нотис при реальном сбое инфраструктуры — по канону, но живой.
- Это nudge промпта/формулировок, не новый механизм; семантические тесты (не по подстроке).

## Генератор интерима (реюз BOB-057)

`InterimLineGenerator.generate(topic, sender_name)` (`interim_line.py`, Tier-0 `TaskType.INTERIM_LINE`) —
без изменений контракта; теперь его зовут ОБА пути. Промпт (`build_interim_line_user_prompt`) — живой в
голосе Боба (уже есть); при нужде чуть обобщить, чтобы работал и на «поиск по запросу» (tool-loop), и на
«сверка факта» (verify).

## 🔴 Отказоустойчивость / инварианты

- **Ноль скриптованности (US-2):** зашитых фраз в коде нет; сбой генерации → **тишина**, не шаблон.
- **Декоративность:** интерим никогда не блокирует поиск/не ломает ход (сбой → тишина).
- **Латентность:** живой интерим — лёгкая Tier-0 (+1–2с, тонет в 45–110с поиске).
- **Инвариант BOB-053:** честный хедж при реальном сбое — цел (только звучит живее, не робо-отчётом).
- **BOB-057 verify-триггер / BOB-055 стриминг** — не трогаем (меняем только ГОЛОС интерима/подачи).

## Слои (DDD)

- **application:** `progress_announcer.py` (вырезать зашитое, живой `_announce_live`); `tool_loop.py`
  (передать query); `handle_message.py` (оба анонсера с генератором + sender; register-nudge заметки).
- **domain/infrastructure:** `interim_line.py` контракт не меняем (возможно чуть обобщить промпт).

## Риски и митигации

- **Тишина вместо анонса при флапе Tier-0** → приемлемо (интерим декоративен; Боб вернётся с ответом);
  это осознанное решение owner («не шаблон»).
- **Register-nudge слишком слаб/силён** → семантические тесты «звучит как Боб, не отчёт»; держать nudge
  мягким (не ломать синтез).
- **tool-loop без query** (аргументы пусты) → generic-topic «поиск» → всё равно живой, не шаблон; либо
  тишина.
- **Регрессия verify-интерима** (убрали fallback) → тест «сбой генератора → тишина, не seeded».

## Открытые решения (под утверждение)

1. **Удалить `WEB_SEARCH_PROGRESS_PHRASES` полностью, сбой→тишина** (не seeded-fallback) — **рекомендую**
   (решение owner: ноль скриптованности).
2. **Унификация:** оба пути через `_announce_live` (генератор), tool-loop передаёт query как topic —
   **рекомендую**.
3. **Register-nudge находки/хеджа** — мягкий промпт-nudge, семантические тесты — **рекомендую** (в объёме,
   но лёгкий; не переписывать синтез).
4. **Генератор** — реюз BOB-057 `InterimLineGenerator`, контракт неизменен — **рекомендую**.
