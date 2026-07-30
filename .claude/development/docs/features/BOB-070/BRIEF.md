> **Status:** Approved
> **Type:** bug
> **Created:** 2026-07-30
> **Issue:** BOB-070

# BRIEF — Надёжность приёма: поллинг теряет сообщения

## Проблема (реальный латентный баг, найден при диагностике BOB-069)

`multibot._poll_bot` (`src/bob/infrastructure/telegram/multibot.py:396-417`) теряет сообщения на
транзиентных обрывах Telegram — критично перед приходом команды (3+ активных = больше обрывов).

```python
async def _poll_bot(self, registration):
    try:
        updates = await registration.bot.get_updates(offset=self._offsets[identity], timeout=...)
    except (OSError, RuntimeError, TimeoutError) as exc:      # (2) НЕ ловит TelegramNetworkError
        logger.warning(...); return 0
    for update in updates:
        self._offsets[identity] = max(self._offsets[identity], update.update_id + 1)  # (1) offset ДО обработки
        if await self.route(update, identity):                # если route падает → апдейт потерян навсегда
            published += 1
```

**Два дефекта:**
1. 🔴 **Offset сдвигается ДО `await route()`.** Если `route()` бросает (транзиент/downstream-сбой),
   offset уже = `update_id+1` → Telegram считает апдейт доставленным и **не переприсылает** → сообщение
   потеряно. (Симптом BOB-069: обращение owner исчезло.)
2. **Изоляция промахивается.** `except (OSError, RuntimeError, TimeoutError)` НЕ ловит
   `aiogram.exceptions.TelegramNetworkError` (обёртка `ServerDisconnectedError`) → рутинный обрыв
   long-poll роняет весь poll-тик (heartbeat гасит «continuing», но цикл прерывается).

## Решение — инварианты (не терять, но и не зацикливать)

- **INV-a (без потери на транзиенте):** offset для апдейта сдвигается ТОЛЬКО после того, как апдейт
  durably принят (`route()` вернулся без исключения). При сбое `route()` — НЕ сдвигать → Telegram
  переприсылает.
- **INV-b (без poison-loop):** апдейт, стабильно падающий в `route()`, не должен зацикливать приём.
  Ограниченные ретраи (напр. ≤3 переприсылки одного `update_id`) → затем пропустить (сдвинуть offset)
  с ГРОМКИМ логом. (Замечание: после BOB-066 `route→submit` неблокирующий и почти не падает — poison
  редок, но защита обязательна.)
- **INV-c (изоляция сети):** `TelegramNetworkError`/`ServerDisconnectedError` при `get_updates`
  ловится в per-bot обработчике → лог + `return 0` + ретрай на следующем тике; НЕ бросает весь тик.
  Разные боты изолированы (сбой одного не глушит другой).
- **INV-d (таск не умирает):** poll-таск переживает любой транзиент и продолжает приём.
- **INV-e (порядок внутри чата сохранён):** апдейты чата по-прежнему обрабатываются по возрастанию
  `update_id`; частичный сбой батча не переставляет остаток.

## Реализация (seam)

`src/bob/infrastructure/telegram/multibot.py` `_poll_bot`:
- Сдвигать `self._offsets[identity]` ПОСЛЕ успешного `route()`; на исключении `route()` — per-update
  `try/except` (лог), НЕ сдвигать (кроме poison-cap INV-b).
- Расширить `except` вокруг `get_updates` до `aiogram.exceptions.TelegramNetworkError` (импорт) —
  либо ловить broadly сетевые + логировать. Сохранить isolation-семантику (`return 0`).
- Poison-cap: лёгкий per-`update_id` счётчик неудач (в памяти воркера), сброс при успехе.

## Беады
```
BOB-070 [bug] (bob-d60) — поллинг теряет сообщения
├── .1 [dev]  — _poll_bot: offset-после-обработки + per-update try/except + poison-cap + ловить TelegramNetworkError
├── .2 [test] — unit: транзиент-фейл route → offset НЕ сдвинут (redelivery); poison ≤3 → skip+log; TelegramNetworkError изолирован; порядок. deps .1
├── .3 [review] — INV-a..e + нет двойной обработки + poison-cap корректен. deps .2
└── .4 [tech-writer] — docs (telegram/multibot надёжность приёма). deps .3
```

## Критерии приёмки
- route падает транзиентно → offset НЕ сдвинут, апдейт переприсылается (не потерян).
- poison-апдейт (стабильно падает) → после ≤3 попыток пропущен + громкий лог (не зацикливает).
- `ServerDisconnectedError`/`TelegramNetworkError` при get_updates → изолирован, тик не падает, таск жив.
- pytest/mypy --strict/ruff/beadloom ci зелёные.

## Заметка
Mutation — не гейт (infra-адаптер, вне MUTATION.md §2). Покрытие — unit-инварианты + resilience.
