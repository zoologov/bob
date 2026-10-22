<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-116 — Здоровье LLM-стека: состояние, сигнал владельцу, зонд, выкатка

> **Last updated:** 2026-10-21
> **Phase:** Completed
> **Ветка:** `features/BOB-116` · **Родитель:** `bob-i83` · **Спеки:** PRD / RFC / CONTEXT / PLAN — Approved 2026-10-21

---

## Current Bead

**Нет — работа завершена.** Последняя беада — TW `bob-i83.14` (доки, VISION, Issues, ROADMAP,
проектный слой, статусы спек). PR #147 открыт 2026-10-22.

## Beads

| Bead | Tracker | Status |
|---|---|---|
| D1 ядро+порты | bob-i83.1 | ✓ done (45/45, 144 мутанта 100 %; API: record_* async, HealthView.failing_since datetime, failed_probes) |
| D2 classify_failure 401/403 | bob-i83.2 | ✓ done (389/389 acceptance, router 242/242, 41 мутант 100 %; S25/S26) |
| D7 OUTAGE_RECOVERED | bob-i83.3 | ✓ done (145/145; SelfAction.outage: OutageSpan — не detail; visibility решает вызывающий) |
| D8a лоадер + bob.vps.yaml | bob-i83.4 | ✓ done (72/72 config; env по типу дефолта, таймауты float, owner_name в .env; гард чистоты) |
| D9 spike qwen3:8b | bob-i83.5 | ✓ done — **A отклонён**: REFLECT 116 с холодный / 76 тёплый (порог 90), классификатор 39 / 4 (порог 15), обе модели 7,1 ГБ > 5,8 доступных → взаимное вытеснение; модель снята, VPS в исходном состоянии; Q5: autobiography=true |
| D3 монитор | bob-i83.6 | ✓ done (125 тестов; loopback 16/16 без двойного учёта; understudy_probe.py) |
| D4 owner_alert | bob-i83.7 | ✓ done (10/10, таймаут 5 с, NoopOwnerAlert) |
| D5 health_gated | bob-i83.8 | ✓ done (76/76; signature без clock; LLM-отказ по дельте consecutive_failures — D3 обязан await record_failure до re-raise) |
| D6 GUPPI /status | bob-i83.9 | ✓ done (114/114 telegram -k; render_health_status в health_status.py; часовой пояс — 3 пояса) |
| D8b деплой | bob-i83.10 | ✓ done (53 теста; deploy/check_config.py; валидация до копии; RUNBOOK §9–10; actionlint/shellcheck 0) |
| D10 сборка | bob-i83.11 | ✓ done (8510 passed; 18 тестов; две находки → D11) |
| D11 fix: старт без дублёра по-настоящему + единый часовой пояс | bob-i83.15 | ✓ done (8590 passed; stand_down в startup; kernel/local_time; 12 саботажей) |
| D12 fix: лог монитора в локальном поясе | bob-i83.16 | ✓ done (30/30; слепая зона «тот же день» закрыта тестом) |
| T тесты | bob-i83.12 | ✓ done (12 сценариев, 11 зелёных + S5 xfail → D13; mutation 144/144 · 41/41 · 19/19) |
| D13 fix: сервисная дверь не роняет ход (S5) | bob-i83.17 | ✓ done (шов LLMRouter.run_optional; настроение + пересмотр черновика; S5 зелёный, xfail снят; 8656 passed / 17 skipped; 5 саботажей) |
| R ревью | bob-i83.13 | ✓ ISSUES: 0 critical, 6 Major (M1 Tier-1 в ToolLoop без доклада; M2 гейт глушит дорожки при живом дублёре; M3 дубли русского рендера; M4 гард деплоя обманывается; M5 оси personality/presence; M6 43 устаревшие пары → TW), 9 minor, 8 notes |
| F1 (M1) Tier-1 обёрнут репортёром | bob-i83.18 | ✓ done (SelfReportingProvider; 31 тест; S13) |
| F2 (M2) гейт по эффективному Tier-0 | bob-i83.19 | ✓ done (20/20 reflect при живом дублёре; TIER0_EFFECTIVE «tier0», правило одно — _tier0_mute) |
| F3 (M3) kernel/ru_text — один дом рендера | bob-i83.20 | ✓ done (131 тест; mutation 149/149; три потребителя краснеют от одной поломки) |
| F4 (M4+m3+RUNBOOK+Q5) гарды деплоя/id, RUNBOOK §10.2, autobiography в конфиге | bob-i83.21 | ✓ done (245/245; обман TRACKED→LIVE даёт 3 FAILED) |
| R2 повторное ревью Majors | bob-i83.22 | ✓ M1–M5 закрыты (обманы красные); 2 новых Major: N1 обёртка бьёт в мёртвое облако при живом дублёре (~2880/день), N2 текст VOICE_DOWN неправдив на пути владельца; 6 minor, 4 notes |
| G1 (N1+m3+m6) обёртка читает здоровье, TIER0_EFFECTIVE в kernel | bob-i83.23 | ✓ done (loopback: 25 тиков → 4 вызова облака = зонды 60/120/300/300, было 25) |
| G2 (N2+m5+m1) тексты владельцу правдивы и человечны, RUNBOOK §10.2, id-гард типографские дефисы | bob-i83.24 | ✓ done (8883 passed; S14; mutation ru_text 151/151 — перемер координатора) |
| TW доки | bob-i83.14 | ✓ done (46 устаревших пар → 0 на чистом индексе; VISION §7.1, Issues #64 закрыт + #71/#72, ROADMAP, проектный слой П.0.2/П.0.3 п.3, RFC «Отклонения») |

## Progress

- [x] task-init: оси (Explore, два seed'а), PRD c38395c, RFC 4f65884, CONTEXT+PLAN утверждены, 14 беад, DAG проверен (`bd ready` = ровно W1)
- [x] W1 + W2 (без D8b) — коммит 02071bf; гейты координатора: 8492 passed / 17 skipped, ruff/mypy чисты, lint 0 + sync 0 на чистом индексе 9.0.0; mutation D1 перемеряется в T (серийно)
- [x] D8b + D11 — коммит 29b6ca3; гейты координатора: 8590 passed / 17 skipped, ruff/mypy чисты, lint 0 + sync 0 на чистом индексе 9.0.0
- [x] W3 (D10) — находки: старт без дублёра не пересобирал провайдеров, пояса UTC vs локальный → fix-беада D11 (bob-i83.15) блокирует T
- [x] T + D12 + D13 — коммиты a0c4ba3, 5218e81
- [x] R — ISSUES (6 Major) → F1–F4; M5 закрыт правкой осей RFC (personality/presence → yes, датировано); долг `bob-qnl` (11 сайтов except Exception)
- [x] F1–F4 — коммит b4ed1d5; гейты координатора: 8855 passed / 17 skipped, ruff/mypy (src+tests) чисты, lint 0 на чистом индексе 9.0.0
- [x] R2 — ISSUES (2 новых Major) → G1, G2; m2/Q6 закрыты в RFC; долги `bob-hod` (DM-уведомление GUPPI в тему), `bob-oqs` (_plural_hours)
- [x] G1, G2 — коммит (см. git log); гейты координатора: 8883 passed, ruff/mypy чисты, lint 0, ru_text 151/151
- [x] TW — доки и статусы спек (bob-i83.14)
- [x] Коммит TW 6040790 → `beadloom ci` PASS на чистом индексе 9.0.0 → портал 23abd2d → **PR #147** (2026-10-22), ждёт required `ci` и мёрж владельца

## Вне этой работы (зафиксировано)

- **Живой смоук** (порча ключа Tier-0 на VPS → сигнал → «восстановился») и **миграция id/секретов в `.env`
  на VPS** — при выкатке тегом **BOB-118** (`bob-sgm`), с явным «да» владельца на каждое действие; результат
  — сюда, в «Results».
- Q5 (`memory.autobiography` на VPS) — решён: `true` в трекаемом `config/bob.vps.yaml` (F4); что
  старый файл на VPS задавал иначе, покажет `compare-keys` при миграции (RUNBOOK §9.2 п.3).

## Results

- **Живой смоук §10.2 на VPS (2026-10-22 06:36–06:39 IST, код `main` 69c3c21 с BOB-124):** облако отрезано процессу `bob`
  (iptables, 2 адреса) в 06:36:50 → `LLM health tier0-primary: healthy → degraded (connection, 5 failures, since 06:37:11)`
  в 06:37:43 (одна строка WARNING; до порога — 5 строк «no fallback» со стеком, как и прежде) → правила сняты 06:37:51 →
  зонд через 54 с: `degraded → healthy (connection, down since 06:37:11)` в 06:38:45, 0 ошибок после → эпизод автобиографии
  «я молчал 22 октября с 06:37 до 06:38 +05:30 (минуту): до облака было не достучаться, думать было нечем. Теперь снова
  могу.» Сообщения владельцу в личку — подтверждает владелец. Пояс в текстах — пояс процесса на VPS (+05:30, Asia/Kolkata):
  косметика, см. долг ниже.
- **§10.1 (класс `auth`, два рестарта)** — после BOB-124 рестарт стоит 2 с; выполняется следующим.
- **Миграция `.env` (RUNBOOK §9)** выполнена 2026-10-22: 5 переменных добавлено, `require-env`/`validate` exit 0; 41 настройка
  прода перенесена в трекаемый конфиг (PR #148). Выкатка `main` на VPS — после BOB-125 (деплой по ветке брал локальную ветку).

### Числа (зелено на дереве, Darwin arm64, CPython 3.12, окружение проекта; легов CI не заходили)

- **Тесты:** 8883 passed, 17 skipped, 0 failed — полный `uv run pytest` после G1+G2
  (`bob-i83.24`); пропуски — живые смоуки без `BOB_LIVE_*` и проверка «только в GitHub Actions».
  `ruff check src/ tests/` и `mypy src/ tests/` (1115 файлов) чисты.
- **Mutation** (`scripts/mutation.sh`, прогоны строго по одному): `kernel.provider_health` 144/144,
  `application.router.fallback_policy` 41/41, `kernel.local_time` 19/19, `kernel.ru_text` 151/151
  (перемер координатора после G2) — 100 %, выживших нет; триаж промежуточных выживших — в беадах
  D1, F3.
- **Приёмка:** `llm_health.feature` — 14 сценариев (S1–S14; 11 имён PRD + S12–S14),
  `tier0_fallback.feature` — 26 (новые S25, S26). Все на собранной программе с настоящими
  loopback-эндпоинтами.
- **Breaker при живом дублёре (G1, loopback):** 25 тиков монолога по 30 с при мёртвом облаке —
  4 вызова облака (зонды через 60/120/300/300 с) вместо 25.
- **Ревью:** два раунда — R1 (6 Major → F1–F4), R2 (M1–M5 закрыты обманами, 2 новых Major → G1, G2).
- **Доки:** `sync-check` на чистом индексе `beadloom==9.0.0` — 46 устаревших пар → 0.

### Что отгружено

401/403 → класс `auth` → дублёр (служебные двери) и спуск Tier-1 → Tier-0; монитор здоровья
провайдеров (`tier0-primary` / `tier0-understudy` / `tier1`) с сигналом владельцу в личку ботом
Боба без LLM, напоминаниями и «вернулся»; одна строка лога на переход; гейт дорожек heartbeat
по «Tier-0 целиком» с зондом 1 → 2 → 5 мин; breaker облака в композите дублёра; Tier-1 на пути
`ToolLoop` докладывает здоровье; `/status` у GUPPI со снимком; эпизод «я молчал» только после
настоящей немоты; сервисная дверь хода не роняет ход (`run_optional`); снятие неготового
дублёра при старте; один пояс времени и один дом русских слов в ядре; трекаемый
`config/bob.vps.yaml` без id и секретов, приведение env по типу дефолта, проверки выкатки
(`deploy/check_config.py`, `deploy-bob.yml`, RUNBOOK §8–§10).

### Spike A (D9, 2026-10-21)

Числа — `bd comments bob-i83.5`: REFLECT 116 с холодный / 76 с тёплый (порог 90), классификатор
39 / 4 с (порог 15), `qwen3:8b` 5,9 ГБ + `bge-m3` 1,2 ГБ > 5,8 ГБ доступных. Решение по критериям
RFC: `tier0_fallback` на VPS остаётся выключен; B (второй облачный провайдер) или замер `qwen3:4b`
— отдельное решение владельца.

### Отложено (зафиксировано)

- **Живой смоук** (`deploy/RUNBOOK.md` §10) и **миграция id и секретов в `.env`** (§9) — при
  выкатке тегом BOB-118 (`bob-sgm`), каждое действие с явного «да» владельца; результат — сюда.
- **Решение владельца по дублёру на VPS** — вариант B или замер `qwen3:4b`.
- **Долги:** `bob-qnl` (11 сайтов `except Exception` шире шва `run_optional`, P2), `bob-ay8`
  (11 файлов тестов считают корень через `parents[N]`, P2), `bob-hod` (уведомление GUPPI на ход
  в личке уходит в тему группы, P2, Issues #71), `bob-oqs` (`personality/absence._plural_hours`
  → `ru_text.plural`, P3).
- Имя сценария S23 в `tier0_fallback.feature` всё ещё говорит «битый ключ» (после BOB-116 это
  класс `auth`, а не контракт); сценарий проверяет 400, имя не менялось — над ним стоит
  комментарий.
