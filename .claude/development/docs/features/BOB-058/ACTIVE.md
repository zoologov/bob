<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-058 — «Нить связанности в группе» (общий диалоговый тред)

> **Created:** 2026-07-01
> **Parent:** `bob-0bl` · ветка `features/BOB-058`

---

## Текущий фокус

Wave 1 — dev `.1` (общий тред + пер-персона сигналы по автору).

## Беады

| Беад | Роль | Статус |
|------|------|--------|
| `bob-0bl.1` | dev: общий тред + absence/anti-repeat по автору | ✅ done |
| `bob-0bl.2` | test: связность + пер-персона целы | ○ blocked (.1) |
| `bob-0bl.3` | review: регрессии + приватность + DDD | ○ blocked (.2) |
| `bob-0bl.4` | tech-writer + Gate | ○ blocked (.3) |

## Прогресс

- 2026-07-01: PRD/RFC/CONTEXT/PLAN утверждены; беады созданы; координатор запущен (dev `.1`).
- 2026-07-01: dev `.1` реализован. `_replay_person_history`→`_replay_recent_thread` (общий тред `recent_episodes(k)`), вызовы в judgment (~2159) и reply (~1360). Пер-персона сигналы по автору: `_author_label`(=interlocutor.display_name) + `_history_for_author` фильтруют общий тред по метке `<имя>`; `_absence_for(history, interlocutor)` и `_user_turns(history, author)` — absence/anti-repeat считаются по текущему автору. Скоуп-хук в `_replay_recent_thread` (публ→общий; приват→задел). Окно-bump ПРОПУЩЕН (риск: правит app.py+loader+test_dialogue_config; 14 уже широкое, config-driven). +4 теста; suite 3161 pass; ruff/mypy/lint зелёные.

## Решения/заметки

- Диагностика: пер-персона тред (BOB-045) рвёт нить в группе (кейс «ответь Лёше про фильм» → «нет такого сообщения»).
- Фикс: общий тред `recent_episodes(k)`; absence/anti-repeat — по текущему автору (не регрессировать).
- Эпизоды уже размечены `«<имя>: …\nbob: …»` — авторство готово.
