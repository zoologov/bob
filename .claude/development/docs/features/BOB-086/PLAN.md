> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-02
> **Issue:** BOB-086

# PLAN — BOB-086 (DAG)

## Seam-точки
- `infrastructure/telegram/rich.py` `MarkdownToRichMessage._parse_blocks`; aiogram `RichBlockTable(cells:
  list[list[RichBlockTableCell]], is_bordered/is_striped/caption)`, `RichBlockTableCell(align,valign,text,
  is_header,colspan)`. Отправка `send_rich_message` (gateway reply→_send_rich_final).
- `personality/voice.py` brevity `_BREVITY_*`:571-584 + `voice_composer.py` _system_prompt_for directives.

## Беады
```
BOB-086 [feature] — форматирование для удобства (rich Telegram + нативные таблицы)
├── .1 [dev] — КОНВЕРТЕР: rich.py GFM-таблицы | … | → RichBlockTable/RichBlockTableCell (header is_header,
│              align из separator :---:, inline-рендер ячеек); рваная→деградация в paragraph; subset цел.
│              Чистый парсер — mutation-цель. Опц. > details→RichBlockDetails если дёшево.
├── .2 [dev] — VOICE: formatting_directive (палитра+судит-по-контенту+casual-живой) в system_prompt;
│              развести длину/структуру (EXPANSIVE структурен, TERSE casual краткий) + few-shot список багов.
│              Глобально (группа+личка). deps .1
├── .3 [test] — unit (GFM→RichBlockTable header/align/inline/рваная-деградация; subset байт-в-байт;
│              directive на NORMAL/EXPANSIVE не на TERSE) + BDD (S1 структура / S2 таблица→RichBlockTable /
│              S3 casual живой) + mutation ≥85% table-парсер. deps .2
├── .4 [review] — INV-1..4; таблица рендерится нативно; subset не регресс; casual не пере-форматирован;
│              рваный markdown не роняет; DDD. deps .3
└── .5 [tech-writer] — docs (rich.py таблицы/палитра + voice formatting-директива). deps .4
```

## Волны
Dev .1→.2. Test→review→tw→PR→мерж→рестарт→живой смоук.
🔴 Смоук: Боб шлёт в личку отчёт + пример из bob-issues.md НАТИВНОЙ таблицей (открытые issues), + список.

## Риски (RFC)
Пере-форматирование casual → директива «по содержимому» + few-shot + BDD S3; рваная таблица → деградация;
регресс subset → регресс-тест.
