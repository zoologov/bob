> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-02
> **Issue:** BOB-086

# CONTEXT — BOB-086 Форматирование (rich + таблицы)

## Суть
Боб форматирует для удобства (судит по контенту): структура→списки/заголовки/таблицы, casual→живой текст.
Две части: конвертер rich.py (GFM-таблицы→RichBlockTable) + voice-директива (ось структуры). Везде.

## Решения (RFC)
- rich.py: GFM `| … |` → RichBlockTable/RichBlockTableCell (header is_header, align из separator), чистый
  парсер, subset цел, рваная→деградация. Опц. details.
- voice.py: formatting_directive (палитра+по-контенту+не-пере-форматировать) в system_prompt; развести
  длину/структуру (EXPANSIVE структурен, TERSE casual живой); few-shot список багов.
- Рендер send_rich_message/aiogram 3.29 (Bot API 10.1) уже есть.

## Инварианты
INV-1 судит по контенту · INV-2 нативные таблицы · INV-3 не регресс (subset+casual) · INV-4 везде.

## Стандарты
Python 3.12 · DDD/Clean · TDD · BDD · mutation ≥85% (table-парсер) · ruff · mypy(src+tests) · beadloom.

## Границы
Медиа-блоки в конвертере, decide_verbosity, интерактив-механизм BOB-083 — не трогаем.

## Связи
После [[bob-085-terminal-ux]]; rich.py + voice BOB-024; Bot API 10.1 (sendRichMessage/RichBlockTable).
