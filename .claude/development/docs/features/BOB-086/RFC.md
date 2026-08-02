> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-02
> **Issue:** BOB-086

# RFC — Форматирование: rich Telegram + нативные таблицы

## Резюме
Две части: (1) **конвертер** `rich.py` `MarkdownToRichMessage` расширить — GFM-таблицы `| … |` →
`RichBlockTable`/`RichBlockTableCell` (существующий subset цел); (2) **voice/промпт** — научить Боба
форматировать под читателя (палитра + судит по контенту + не пере-форматировать casual), развести длину
и структуру. Рендер (`send_rich_message`) и палитра уже есть (Bot API 10.1 / aiogram 3.29).

## Seam-точки
- Конвертер: `infrastructure/telegram/rich.py` `MarkdownToRichMessage._parse_blocks` (диспетчер блоков:
  code/heading/quote/list/divider/paragraph); inline `RichText*`. Отправка — `send_rich_message`
  (gateway.py, обычный ответ Боба через `reply→_send_rich_final`). Типы aiogram: `RichBlockTable(cells:
  list[list[RichBlockTableCell]], is_bordered, is_striped, caption)`, `RichBlockTableCell(align, valign,
  text: RichTextUnion|None, is_header, colspan, rowspan)`, `RichBlockDetails(summary, blocks, is_open)`.
- Voice: `personality/voice.py` (brevity `_BREVITY_*` :571-584, `brevity_directive`/`brevity_few_shot`;
  `guppi_canon`-прецедент директивы) + сборка `voice_composer.py:_system_prompt_for` (directives list).

## Часть 1 — Конвертер: GFM-таблицы → RichBlockTable
В `_parse_blocks` добавить распознавание GFM-таблицы:
```
| H1 | H2 |
|:---|---:|      <- separator (выравнивание: :--- left / ---: right / :---: center)
| a  | b  |
```
→ `RichBlockTable(cells=[[header cells is_header=True], [row cells], ...])`, `RichBlockTableCell(align=
из separator, text=инлайн-рендер ячейки)`. Чистый парсер (I/O-free) — mutation-цель. Битая/неполная
таблица (нет separator, рваные `|`) → деградирует в текст/paragraph (не падает). Опц. `> [details] …` →
`RichBlockDetails` (сворачиваемое) — если дёшево; иначе отдельный заход. Существующий subset НЕ трогать.

## Часть 2 — Voice: ось СТРУКТУРЫ (по контенту)
- Новая директива `formatting_directive()` (voice.py, рядом с brevity) — в system_prompt (directives
  list voice_composer): «Ты в Telegram с rich-форматированием (заголовки, **жирный**, `код`/```блоки```,
  списки, > цитаты, **таблицы** `| … |`). Форматируй под ЧИТАТЕЛЯ: структурное (списки/шаги/сравнения/
  перечни) — списком/заголовками; табличное — markdown-таблицей; ключевое — жирным; код/пути/команды —
  `моно`. НЕ форматируй ради формата: обычный разговор — живой короткий текст. Судишь по содержимому.»
- Развести длину и структуру: подправить `_BREVITY_EXPANSIVE` (не только «абзацы», а «структурируй, если
  содержимое структурное»); `_BREVITY_TERSE` (casual) — оставить живым/кратким (структура там не нужна);
  few-shot: «список багов → оформленный список/таблица с приоритетами». Директива присутствует на
  субстантивных ходах (NORMAL/EXPANSIVE); на TERSE — не навязывать.
- Глобально (группа+личка) — не привязано к dev/каналу.

## Инварианты → реализация
- INV-1 судит → директива «по содержимому, casual живой»; TERSE не форматируется.
- INV-2 таблицы → GFM→RichBlockTable в конвертере.
- INV-3 не регресс → subset конвертера цел (регресс-тест); TERSE casual краткий байт-в-байт.
- INV-4 везде → voice-директива глобальна.

## Риски
- Модель пере-форматирует casual → директива+few-shot акцентируют «по содержимому, болтовня живая»; BDD S3.
- Битый markdown-table роняет конвертер → деградация в paragraph (тест на рваную таблицу).
- Регресс существующего rich-subset → регресс-тест всех блоков до/после.

## Тесты
- Unit/TDD: GFM-таблица→RichBlockTable (header/выравнивание/inline ячеек; рваная→деградация); subset
  конвертера байт-в-байт; formatting_directive присутствует на NORMAL/EXPANSIVE, отсутствует/не навязан
  на TERSE. **mutation ≥85%** на table-парсере.
- BDD: S1 структурный запрос→структурный markdown (список/таблица), S2 markdown-таблица→RichBlockTable
  (через границу конвертера), S3 casual→живой текст (не пере-форматирован).
- Живой смоук: Боб шлёт в личку отчёт + пример из bob-issues.md **нативной таблицей** (открытые issues).
