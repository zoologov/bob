> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-02
> **Issue:** BOB-085

# PLAN — BOB-085 (DAG + seam-точки)

## Seam-точки
- Рендер: `coding/stream_render.py` (_MAX_TEXT=200:38, _render_text:130, _render_tool/_render_bash,
  _render_tool_result:136, _HANDLERS:151). Отправка: `coding/adapters/live_stream.py` _DmLiveStreamer:65,
  `RichMarkdownSender`/`send_rich_message` + чанк `PLAIN_TEXT_LIMIT=4096` (gateway.py:106). Режим —
  через interactive_session/wiring в стример.

## Беады
```
BOB-085 [feature] — UX интерактив-терминала: полный вывод + rich
├── .1 [dev] — РЕНДЕР: параметризовать stream_render режимом (verbose интерактив: assistant целиком+markdown,
│              вызовы компактно rich, tool-результат щедрый кэп в код-блоке, error моно; verbose=False=груп
│              байт-в-байт) + чистый чанк-хелпер (сплит ≤4096, код-блок не рвётся). Чистые ядра, mutation.
├── .2 [dev] — ПРОВОДКА: интерактив-DM стример шлёт verbose-рендер через RichMarkdownSender (rich+чанкинг);
│              груп-путь BOB-082 краткий (различение режима в interactive_session/wiring). Механизм BOB-083
│              не трогать. deps .1
├── .3 [test] — unit (verbose рендер/груп байт-в-байт/чанк границы+код-блок) + BDD (S1 полный ответ / S2 rich
│              / S4 груп краткий) + mutation ≥85% рендер+чанкер. deps .2
├── .4 [review] — INV-1..4; груп не регресс; markdown-сбой деградирует (не роняет); чанк не рвёт код-блок;
│              механизм BOB-083 нетронут. deps .3
└── .5 [tech-writer] — docs (coding stream_render verbose-режим + интерактив rich UX). deps .4
```

## Волны
Dev .1→.2 последовательно. Test→review→tw→PR→мерж→рестарт→живой смоук.
🔴 Смоук: /code -i → «список багов с приоритетами» → полный форматированный ответ (не огрызок); груп короткий.

## Риски (RFC)
markdown claude ломает парсер → деградация на plain (прецедент BOB-082); чанк рвёт код-блок → хелпер
переоткрывает ```; груп регресс → verbose=False байт-в-байт.
