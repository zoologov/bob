> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-02
> **Issue:** BOB-085

# CONTEXT — BOB-085 UX интерактив-терминала

## Суть
Курированный rich-рендер потока claude в интерактив-DM: полный текст ответов (не 200-символьный огрызок)
+ rich-форматирование (markdown/код-блоки); груп-нарратив BOB-082 остаётся кратким. Закрывает
BOB-Issues #35 (форматирование) + #36 (обрезка).

## Ключевые решения (RFC)
- `stream_render.py` параметризовать режимом (verbose интерактив vs краткий груп); чистое ядро.
- verbose: assistant-текст целиком + markdown passthrough (send_rich_message рендерит), вызовы компактно,
  tool-результат щедро капнут (_MAX_RESULT) в код-блоке, чанкинг ≤4096 (наследуем PLAIN_TEXT_LIMIT).
- `verbose=False` = груп байт-в-байт (INV-4, регресс-тест). Механизм BOB-083 (stdin/kill/authz) НЕ трогаем.

## Инварианты (PRD)
INV-1 полный ответ · INV-2 rich · INV-3 курирование · INV-4 режимы различены (груп не регресс).

## Стандарты (CLAUDE.md §0.1)
Python 3.12 · DDD/Clean · TDD · BDD · mutation ≥85% на рендере+чанкере · ruff · mypy --strict (src+tests) ·
beadloom перед коммитом.

## Границы
Не трогаем интерактив-механизм (stdin/kill/authz/main), Mini-App, brevity-личности Боба.

## Связи
BOB-Issues #35/#36 · надстройка над [[bob-083-interactive-terminal]] + [[bob-082-dev-dm-stream]] (stream_render).
