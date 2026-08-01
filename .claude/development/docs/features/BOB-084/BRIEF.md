> **Status:** Approved
> **Type:** bug (P0)
> **Created:** 2026-08-02
> **Issue:** BOB-084

# BRIEF — Кодер-runner падает на stream-json строке >64 КБ

## Проблема

Интерактивная сессия (BOB-083) **создаётся, но умирает на первом крупном выводе claude**. Из живого лога
(18:41):

```
ERROR bob.coding.usecases.interactive_session: interactive output stream failed for c70b56b4…
asyncio.exceptions.LimitOverrunError: Separator is found, but chunk is longer than limit
  interactive_runner.py:214  raw = await stdout.readline()
```

**Корень:** `asyncio.create_subprocess_exec` создаёт `StreamReader` с дефолтным лимитом буфера **64 КБ**;
`readline()` на строке `stream-json` длиннее 64 КБ (tool-result / чтение файла / длинный ответ claude)
кидает `LimitOverrunError` → asyncio конвертит в `ValueError` → поток вывода `_pump` падает → сессия
уходит в `cancelled`. Owner видит «открылось и сдохло».

**Тот же дефект в one-shot кодере (BOB-039):** `claude_runner.py:145` `create_subprocess_exec` без
`limit=`, `readline()` на :162 — пережил PR #48/#50 (строки были <64 КБ), но это вопрос времени.

**Почему 4772 теста не поймали:** все тесты гоняют **fake-процесс** со скриптованными короткими строками;
лимит 64 КБ — свойство **реального** subprocess-транспорта, которого фейк не моделирует (класс «фейки не
воспроизводят лимит реального транспорта», урок BOB-067).

## Решение

1. **Поднять лимит буфера:** `create_subprocess_exec(..., limit=<generous>)` (напр. константа
   `_STREAM_LIMIT = 16 * 1024 * 1024`) в ОБОИХ спавнерах — `interactive_runner.py` (спавнер ~:246) и
   `claude_runner.py` (спавнер ~:145). Это чинит реальный краш (claude-строки на практике <1 МБ).
2. **Резилентная читалка (belt-and-suspenders):** обернуть `await stdout.readline()` так, чтобы на
   `ValueError`/`LimitOverrunError` (патологическая строка > нового лимита) читалка **не роняла** pump
   необработанным исключением, а завершала поток корректно (лог + graceful end), без зомби. В ОБОИХ
   runner'ах.
3. **Тест-гэп (🔴 обязательно):** тест на РЕАЛЬНОМ subprocess (напр. `python -c` печатает JSON-строку
   >64 КБ) → runner читает её без краша. Без реального-транспорта теста этот класс регрессирует снова.

## Беады

```
BOB-084 [bug] — кодер-runner падает на stream-json >64 КБ
├── .1 [dev]    — limit= в обоих спавнерах + резилентная read_lines (interactive_runner + claude_runner)
├── .2 [test]   — 🔴 РЕАЛЬНЫЙ subprocess отдаёт строку >64 КБ → оба runner'а читают без краша; резилентность на >limit
└── .3 [review] — фикс закрывает LimitOverrunError; нет зомби/утечки; one-shot BOB-039 не сломан; limit разумен
```

## Критерии приёмки

- Интерактивная сессия переживает крупный вывод claude (строка ≥64 КБ и ≥1 МБ) без обрыва.
- One-shot кодер (BOB-039) тем же фиксом устойчив.
- Тест на реальном subprocess с >64 КБ строкой — зелёный (ловит исходный баг).
- Нет осиротевших процессов/worktree; полный pytest зелёный; ruff/mypy(src+tests)/beadloom ci.
- 🔴 Живой смоук: `/code -i` из лички → реальная claude-сессия НЕ обрывается на первом крупном эвенте.

## Связи

Регрессия [[bob-083-interactive-terminal]] (интерактив) + латентно [[bob-081-dev-introspection]]/BOB-039
(one-shot). Урок теста — [[bob-067-repo-navigation]] (реальный негативный smoke обязателен).
