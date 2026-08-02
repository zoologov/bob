> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-02
> **Issue:** BOB-085

# RFC — UX интерактив-терминала (полный вывод + rich)

## Резюме

Различить два режима рендера потока claude: **интерактив-DM** (курированный полный + rich) vs
**груп-нарратив** (краткий, как сейчас). Ядро — `coding/stream_render.py` (сейчас `_MAX_TEXT=200` на всё).
Отправитель (`RichMarkdownSender.send_rich_message` + чанкинг `PLAIN_TEXT_LIMIT=4096`) и `_DmLiveStreamer`
уже есть — переиспользуем; assistant-текст перестаём резать и отдаём markdown, чанкинг наследуем.

## Seam-точки

- **Рендер:** `coding/stream_render.py` — `render_stream_event(event)`; каппы `_MAX_TEXT=200`/`_MAX_CMD=120`/
  `_MAX_ERROR=100` (:38-40); `_render_text` (:130-133, режет до `_MAX_TEXT`), `_render_tool`/`_render_bash`
  (компактные строки), `_render_tool_result` (:136). `_HANDLERS` (:151-158).
- **Отправка:** `coding/adapters/live_stream.py` `_DmLiveStreamer.stream` (:65-94, `notifier.send(line)` +
  rolling `panel`); `OwnerNotifier`→`_CodingOwnerNotifier`→`RichMarkdownSender.send(chat_id, markdown)`
  (`gateway.py`), `send_rich_message` (rich markdown→heading/list/code), чанкинг `PLAIN_TEXT_LIMIT=4096`
  (`gateway.py:106`).
- **Режим:** интерактив идёт через `interactive_session` → тот же `LiveRunStreamer`/`_DmLiveStreamer`;
  груп-нарратив BOB-082 — через `_narrate_run` (кап). Нужно передать «режим рендера» в стример/рендер.

## Дизайн

### Поток 1 — Курированный rich-рендер (интерактив)
`stream_render.py` параметризовать режимом (напр. `render_stream_event(event, *, verbose: bool=False)`
или отдельная `render_stream_event_rich`), чистое ядро (mutation-цель):
- **assistant-текст:** в verbose — **НЕ резать** (или очень щедрый кэп); отдавать **markdown как есть**
  (claude уже markdown) → `send_rich_message` отрендерит заголовки/списки/`код`. Схлопывание пробелов —
  аккуратно (не ломать код-блоки).
- **вызовы инструментов:** компактные rich-строки — `✏️ правлю \`path\``, `📄 читаю \`path\``,
  `$ \`command\`` (моно/код), `🔍 ищу «pattern»`. Каппы команд/путей умеренные.
- **tool-результаты:** щедрый кэп (напр. `_MAX_RESULT ~1500`) в ``` код-блоке ``` + «…(обрезано)» если
  длиннее — не полный дамп (INV-3 курирование).
- **error:** в `код`/моно, читаемо.
Груп-режим (`verbose=False`) = текущее поведение байт-в-байт (INV-4).

### Поток 2 — Проводка + чанкинг rich в интерактив-DM
- `_DmLiveStreamer` (или его интерактив-вариант) вызывает рендер в verbose-режиме и шлёт через
  `RichMarkdownSender` (rich + существующий чанкинг ≤4096). Assistant-ответ длиннее 4096 → авто-сплит
  (наследуем `PLAIN_TEXT_LIMIT`); проверить, что `send_rich_message` либо чанкит, либо на длинном падает
  в чанкенный plain — если рендерер целиком не чанкит rich, добавить чистый **чанк-хелпер** (mutation-цель)
  сплита по строкам/код-блокам ≤ лимита и слать по кускам.
- Различение: `interactive_session`/wiring передаёт verbose-стример; груп-путь BOB-082 — краткий (как сейчас).
- 🔴 Механизм BOB-083 (stdin/kill/authz) НЕ трогаем — только рендер+отправка вывода.

## Инварианты → реализация

- INV-1 полный → verbose не режет assistant + чанкинг ≤4096.
- INV-2 rich → markdown passthrough + `send_rich_message`; код/команды в код-блоках.
- INV-3 курирование → assistant целиком, tool-результат щедро капнут, вызовы компактны.
- INV-4 режимы → `verbose=False` = груп байт-в-байт (регресс-тест).

## Риски

- **Markdown claude ломает Telegram-парсер** (незакрытый ```/спецсимволы) → `send_rich_message` уже
  деградирует на plain при rich-сбое (BOB-082 прецедент санитайза); тест на «грязный» markdown.
- **Чанк рвёт код-блок** → чанк-хелпер сплитит по границам и переоткрывает ``` на стыке (тест).
- **Груп-нарратив регресс** → verbose=False байт-в-байт; BDD S4.
- **Слишком длинный tool-дамп** → `_MAX_RESULT` кап (курирование).

## Тест-стратегия

- **Unit/TDD:** verbose-рендер (assistant целиком+markdown, tool компактно, tool-результат кап в код-блоке,
  error), груп-режим байт-в-байт; чанк-хелпер (границы, код-блок не рвётся, ≤лимит) — **mutation ≥85%** на
  рендере+чанкере.
- **BDD `.feature`:** S1 полный ответ (длинный текст доходит целиком, не 200), S2 rich (код-блок/список),
  S4 груп краткий (не регресс) — через границу (fake notifier ловит отправленное).
- **Живой смоук:** `/code -i` → «список багов с приоритетами» → полный форматированный ответ (не огрызок);
  длинный вывод чанкится; груп-стрим короткий.
