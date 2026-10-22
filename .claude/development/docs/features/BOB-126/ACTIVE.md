<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE — BOB-126

> **Ветка:** `features/BOB-126` · **Спека:** [BRIEF.md](BRIEF.md) · **Беада:** `bob-9kk` · **Обновлено:** 2026-10-22

## Прогресс

- [x] BRIEF утверждён (владелец, 2026-10-22)
- [x] конфиг дублёра + keep_alive drop-in + owner_address + TZ + деплой/bootstrap/RUNBOOK + тесты
  (dev `bob-9kk`, 2026-10-22; детали и саботаж — в комментариях беады)
- [ ] PR, мёрж, выкатка, живая проверка (/status, ollama ps, смоук §10.2 на дублёре)

## Results

- `config/bob.vps.yaml`: дублёр `ollama` / `qwen3.5:4b` с числами BOB-123 в комментарии;
  гард чистоты конфига дополнен ключом `owner_address`.
- `deploy/ollama-keep-alive.conf` (новый) ставится выкаткой до `ollama pull` и bootstrap'ом
  до модели дублёра; `deploy/bob.service` с `TZ=Europe/Moscow` ставится выкаткой до рестарта.
  Оба — только при отличии содержимого (`cmp -s`).
- `telegram.owner_address` (дефолт пусто, `BOB_TELEGRAM__OWNER_ADDRESS`): обращение в
  сигналах владельцу; без него — первое слово `owner_name`.
- `deploy/RUNBOOK.md` §11 «Дублёр Tier-0 на VPS», §10.2 — ожидание с дублёром, §9.1 — новая
  переменная.
- После `systemctl restart ollama` выкатка и bootstrap ждут ответа `ollama ps` до 30 с:
  `systemctl` возвращается до того, как Ollama слушает порт, и pull ушёл бы в закрытый порт.
- Замер на дереве (Darwin arm64, CPython 3.12.12; CI-лег ubuntu-latest не измерялся): полный
  pytest 8930 passed, 17 skipped; ruff и mypy (src, tests) чисто; actionlint и shellcheck
  `deploy/bootstrap.sh` чисто; `beadloom==9.0.0` на чистом индексе — `lint --strict`,
  `sync-check`, `ci` с кодом 0.
- `deploy/bob.service`: `After=` и `Wants=ollama.service` (решение координатора 2026-10-22).
  Без них после перезагрузки VPS проверка дублёра при старте могла уйти в порт, который Ollama
  ещё не слушает, и дублёр был бы снят до перезапуска.
- Ревью `bob-9kk` (1 Major, 6 Minor) исправлено, 2026-10-22:
  - M1: восприятие реакции снято с пути поллинга — подписчик ставит реакцию в `SerialQueue`
    (один воркер, порядок поступления), тест на настоящем `MultiBotGateway.poll_once`;
  - m1: drop-in, не применённый из-за отказа `daemon-reload` или `restart ollama`, убирается, а
    юнит bob возвращается к прежнему, поэтому следующая выкатка снова видит отличие (выкатка и
    bootstrap);
  - m3: тест «у юнита bob нет жёсткой зависимости от Ollama» (`Requires=`, `Requisite=`,
    `BindsTo=`, `PartOf=`);
  - m2, m5, m6: формулировки про проверку дублёра при старте (одна, 5 с, без повтора),
    заголовок Issues #68, таблица Axes в BRIEF.
- Замер после фиксов (Darwin arm64, CPython 3.12.12, на дереве): полный pytest 8945 passed,
  17 skipped; ruff и mypy (1121 файл) чисто; `beadloom ci` на чистом индексе — 0.
- Живая проверка после выкатки — за владельцем/координатором (пункт ниже).
