# ACTIVE: BOB-094

> **Обновлено:** 2026-08-18

## Сейчас
Спека готова (PRD/RFC/CONTEXT/PLAN, все Approved), расширена owner'ом до CI/CD. 8 беад, DAG
проставлен. Первая волна: срез 3 (ops-артефакты, `deploy/`) ∥ срез 2 (наблюдаемость «оглох», `src/`)
— непересекающиеся файлы.

### bob-jgm.1 (dev, объявление рестарта) — ГОТОВО (ждёт верификации координатора)
Человечное объявление рестарта голосом Боба (BOB-090.D). ВСЕ гейты зелёные:
- Чистое ядро `proactivity/restart_voice.py::restart_voice(RestartMoment, *, marker)` — 5 живых
  вариантов на LEAVING/RETURNED, детерминированный выбор по SHA-256(marker) (без random/времени).
  mutation: 13 мутантов, 12 killed, 1 equivalent (`encode("UTF-8")` vs `"utf-8"` — codec тот же).
- Use-case `proactivity/usecases/announce_restart.py::AnnounceRestart` — таймаут (asyncio.wait_for)
  + best-effort; порты `RestartNotifier` / `RestartMarkerStore`.
- Адаптеры: `infrastructure/telegram/restart_notifier.py::_RestartNotifier` (owner-DM + топик),
  `proactivity/adapters/restart_marker_store.py::KvRestartMarkerStore` (маркер + epoch в kv).
- Хуки в `runtime/composition.py`: shutdown ДО закрытия транспорта → announce_leaving; startup →
  announce_returned (по маркеру). Флаг `runtime.restart_notice` (default OFF → байт-в-байт).
- Тесты +34: 7955 passed / 16 skipped. ruff/mypy(src+tests) чисто. lint 0 violations, sync-check
  660 fresh, beadloom ci PASS.

### bob-jgm.2 (dev, наблюдаемость «оглох») — В РАБОТЕ
Поверх счётчика BOB-103 `_poll_failures[identity]`:
- Чистое ядро `kernel/poll_outage.py::outage_state(consecutive_failures, threshold) -> bool`
  (mutation-цель, source_paths). Порог > 1: единичный блип ≠ оглох.
- multibot: переход в «оглох» → WARNING-диагноз РОВНО раз; восстановление (первый успех после
  оглох) → снятие РОВНО раз. Не спам на каждый сбой.
- Порог из `telegram.outage_threshold` (дефолт `_DEFAULT_OUTAGE_THRESHOLD`).
- Полноценный Telegram-алерт НЕ делаем — оглохший Боб сам о себе не напишет (ограничение в
  докстроке, честно; сигнал через лог + `./bob status`).

## Решения owner'а
VPS есть (Ubuntu/apt) · дублёр на VPS нет (честное молчание) · секреты в GitHub Secrets · деплой по
тегу v* · объявление рестарта: личка+группа, голосом Боба.

## 🔴 Owner-gated (живой выкаткой, не кодом)
Первичная установка на VPS, значения секретов в GitHub, первый перенос data/bob.db, VPS SSH-ключ.
Критерий «деплой поехал» = реальная выкатка (урок BOB-088: отгрузка ≠ активация).
