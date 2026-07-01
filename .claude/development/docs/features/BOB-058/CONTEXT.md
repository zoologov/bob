<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-058 — «Нить связанности в группе» (общий диалоговый тред)

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD/RFC:** `./PRD.md` · `./RFC.md`

---

## Суть (одним абзацем)

Точечный фикс в `HandleMessage`: разговорный тред для контекста суждения+ответа переключается с пер-персона
(`recent_episodes_for(sender_id,k)`, BOB-045) на **общий тред топика** (`recent_episodes(k)` — порт есть,
эпизоды уже размечены `«<имя>: …\nbob: …»`). Боб слышит всю группу, держит нить многосторонней беседы.
Пер-персона сигналы (absence-hint по автору, anti-repeat по автору) считаются отдельно и не ломаются;
relationship/first-impression не трогаем (свои per-sender сторы).

## Ключевые решения (утв. в PRD/RFC)

1. **Общий тред** `recent_episodes(k)` для reply/judgment-контекста (пер-персона — только для absence/
   anti-repeat).
2. **absence-hint** — фильтр общего треда по текущему автору (без доп. I/O, graceful).
3. **Скоуп:** публичная группа → общий тред; приват/DM → пер-персона (задел, без реализации лички).
4. **Окно** `dialogue.recent_turns` — конфигурируемо; небольшой bump дефолта для группы (деталь).

## Архитектура (где что менять)

- **application** (`application/usecases/handle_message.py`):
  - `_replay_person_history` → `_replay_recent_thread` (отдаёт `recent_episodes(self._recent_turns)`, общий
    тред). Вызовы в `_judge_turn` (~2159) и reply (~1357) — те же.
  - **absence-hint** (`_absence_for`): last-seen по текущему автору — фильтр общего `history` по `<имя>`
    отправителя (graceful: нет хода в окне → нет хинта).
  - **anti-repeat** (`is_user_repeat`/`_user_turns` ~1367/3258): `_user_turns` фильтровать по текущему
    автору (`<имя>`), чтобы «повтор» проверялся по ЭТОМУ человеку.
  - скоуп-хук: публичная группа → общий (комментарий/задел для приват/DM).
- **domain/infrastructure:** без изменений (порт `recent_episodes` есть; формат эпизода уже с авторством).

## 🔴 Инварианты (НЕ нарушать)

- **US-4 пер-персона сигналы целы:** absence-hint по текущему человеку; relationship (BOB-014) +
  first-impression (BOB-019) по sender_id (свои сторы) — НЕ регрессируют. Тест-инвариант на каждый.
- **anti-repeat корректен:** повтор проверяется по репликам ТЕКУЩЕГО автора, НЕ по чужим (иначе чужая
  похожая реплика ложно «повтор»).
- **Связность (US-1/2/3):** Боб видит сообщения ДРУГИХ участников в свежем треде (кейс «ответь Лёше про
  фильм»); различает авторов (метки `<имя>:`).
- **Приватность:** общий тред ОК в публичной группе (BOB-051 — память публична); приват (будущее) —
  пер-персона. Внутрянка/owner-приват в тред не попадают (обычные сообщения топика).
- **Graceful:** сбой чтения треда → best-effort (как `_others_present`), ход не ломается.
- **Floor/адресность (BOB-023/025)** — переиспользуются поверх общего треда, поведение сохраняется.
- **DDD:** application-only; порт `recent_episodes` не меняем; композиция как есть.

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio; **DDD + Clean Architecture**. `ruff`, `mypy --strict`; без `Any`/`# type:
  ignore` без причины. TDD; покрытие ≥ 80% (`mypy src tests`). Без `print`/`breakpoint`, bare `except`,
  `import *`, mutable-default. Русские литералы → per-file-ignore RUF001/002/003.

## Реюз / прецеденты

- `recent_episodes(k)` — общий тред, уже используется `_others_present` (BOB-023).
- `recent_episodes_for(sender_id,k)` — пер-персона (BOB-045), больше НЕ для контекста (можно оставить для
  absence или заменить фильтром).
- Формат эпизода `«<имя>: …\nbob: …»` (`sqlite_repo`) — авторство готово.
- `_absence_for` / `is_user_repeat` / `_user_turns` — точки правки пер-персона сигналов.

## Связи

BOB-045 (пер-персона тред — фиксим) · BOB-051 (память публична — основание) · BOB-023/025 (floor/
адресность) · BOB-014 (отношения) · BOB-019 (идентичность) · BOB-032 (anti-repeat). Север:
`bob-social-identity-strangers`, `bob-telegram-pivot`.
