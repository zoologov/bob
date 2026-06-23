<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-022 — Фикс: Боб повторяется дословно

> **Phase:** Done
> **Updated:** 2026-06-23
> **Branch:** `features/BOB-022`

---

## Текущий фокус

Все волны завершены. Эпик готов к PR.

## Прогресс

| Бид | Роль | Статус | Что сделано |
|-----|------|--------|-------------|
| bob-9x3.1 | dev | Done | Сэмплинг по тирам: `OpenAICompatProvider` кладёт `temperature`/`top_p` в payload на всех путях; `build_tier_providers` прокидывает per-tier; конфиг `llm.tier0_temperature`=0.5 / `llm.tier1_temperature`=0.8 (env-override). Анти-повтор-страж в `handle()` (одна регенерация при дословном дубле прошлого ответа Боба). DIAG-лог убран. |
| bob-9x3.4 | dev | Done | Реакция на повтор собеседника: `domain/personality/conversation.py` `is_user_repeat` (нормализованный exact-match по недавним ходам пользователя) + `voice.user_repeat_directive()`; врезка в `_system_prompt_for` через `handle_message`. |
| bob-9x3.2 | review | Done | Причина устранена, регрессий нет, оба стража работают. |
| bob-9x3.3 | tech-writer | Done | `docs/architecture.md` (RU): сэмплинг temperature (конфиг + payload), два разных стража (собственный анти-повтор Боба vs директива на повтор пользователя `is_user_repeat`/`user_repeat_directive`), их место в потоке ответа; раздел тестов BOB-022. Re-baseline точных пар; Gate зелёный. |

## Решения

- **Причина дословного самоповтора:** мы не задавали `temperature` → Qwen MaaS декодировал жадно (одинаковый ввод → одинаковый вывод). Подтверждено живым DIAG-логом.
- **Два слоя защиты:** (1) сэмплинг temperature в payload (первичный фикс); (2) анти-повтор-страж в `handle()` (защита в глубину, регенерация максимум один раз).
- **Реакция на повтор пользователя** — отдельная механика: детекция (`is_user_repeat`, чистый предикат) + голос (`user_repeat_directive`), консервативный exact-match после нормализации, чтобы не ложнить.

## Критерии приёмки

- [x] Разные входящие → разные ответы (дословного повтора нет).
- [x] Анти-повтор-страж: дословный дубль прошлого ответа → регенерация.
- [x] anti-bait/язык/выражение/память/тиринг не сломаны; `ruff`/`mypy --strict`/`beadloom ci` зелёные.
