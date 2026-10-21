<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-116 — Здоровье LLM-стека: состояние, сигнал владельцу, зонд, выкатка

> **Status:** Done
> **Завершён:** 2026-10-21 (ветка `features/BOB-116`)
> **Created:** 2026-10-21
> **PRD:** [PRD.md](PRD.md) (Approved 2026-10-21) · **Беада:** `bob-i83`

---

## Overview

Боб получает **явное состояние здоровья LLM-провайдеров** (`healthy → degraded → recovered`) с чистым
ядром в `kernel`, которое питается исходами каждого вызова из роутера и из дублёр-обёртки. Переходы
состояния дают три наблюдаемых следствия: **сообщение владельцу в личку** без участия LLM (с
напоминаниями по расписанию и «восстановился»), **режим зонда** для LLM-зависимых дорожек heartbeat
(вместо 30-секундного долбления) и **одну строку лога на переход**. Отказ авторизации/квоты (401/403)
перестаёт быть «контрактом» и становится недоступностью: при подключённом дублёре вызов уходит к нему.
GUPPI `/status` показывает снимок здоровья; после восстановления Боб записывает себе эпизод о простое.
Конфиг прода для `llm` становится трекаемым файлом без секретов и идентификаторов, который привозит
деплой; дублёр на VPS решается **замером** (spike) по критериям ниже.

## Motivation

### Problem
Четыре пробела PRD: политика дублёра не считает 401/403 отказом (`fallback_policy.py:103-113`);
сервисные двери Tier-0 без эскалации (`llm_router.py:274-312`); нет счётчика/breaker'а/сигнала —
`periodic` логирует стек и спит фиксированный интервал (`application/runtime/heartbeat.py:60-87`),
единственный латч «один раз на смену состояния» есть только у поллинга (`multibot.py:354-625`,
log-only); конфиг прода не трекается и не едет деплоем (`deploy-bob.yml:66-87`, `.gitignore:58-62`).
Замер VPS 2026-10-21: Tier-1 тоже ловил 403 (`Tier 1 failed on room_read with a CONTRACT failure`,
2026-08-31) — **один домен отказа** для обоих тиров; шум вне окон 403 — 1–4 строки/день.

### Solution
Чистое ядро состояния + порт наблюдателя в `kernel` (единственное место, куда могут смотреть и
`application`, и `infrastructure` без нарушения `application-no-infra`); монитор в `application/router`
как единственная точка, через которую идут все LLM-вызовы (`LLMRouter.run`; исключение `ToolLoop` —
см. Changes); адаптеры в `infrastructure/telegram`; гейт дорожек — в `runtime/wiring/proactivity.py`,
где дорожки и собираются; конфиг — отдельный трекаемый файл + шаг деплоя.

## Technical Context

### Constraints
- Python 3.12, asyncio, aiogram 3.x, mypy --strict, ruff; `kernel` — только stdlib и `typing`
  (`kernel/__init__.py:8-31`, правила `kernel-no-*`), поэтому ядро состояния не знает про aiohttp:
  классификацию ошибки в «класс отказа» делает вызывающий слой.
- `application/**` не импортирует `infrastructure/**` (`rules.yml:99-102`); порядок слоёв
  runtime > infra > application > domain. Порт сигнала владельцу — в `kernel/ports.py`.
- Политика приватности VISION §7.1 не меняется: `who_may_answer_for_bob` (`voice_integrity.py:56-94`)
  остаётся как есть; дублёр отвечает только за сервисные двери, голос — только Tier-1 с редакцией.
- Mutation-цели — чистые функции модуля, **не** методы `@dataclass` (слепая зона mutmut, MUTATION.md).
- Репозиторий **публичный** — трекаемый конфиг прода не содержит ни секретов, ни идентификаторов
  (chat/owner id); они живут в `/opt/bob/.env` через `BOB_<section>__<key>`.
- VPS: 4 vCPU Xeon Gold 6248, GPU нет, RAM 7.9 ГБ (доступно 5.8), диск 69 ГБ свободно, Ollama 0.32.14.

### Affected Areas
Роутер и политика дублёра; дублёр-обёртка; heartbeat-дорожки и их сборка; телеграм-адаптеры (GUPPI,
нотификатор владельца); конфиг-лоадер; память (автобиография); деплой. Узлы — в таблице осей.

## Axes

> **Derived by:** `beadloom impact` 9.0.0 over `src/bob` — два прогона: seed-файл
> `src/bob/application/router/fallback_policy.py` и `src/bob/application/router/llm_router.py`
> **Seed:** прогон 1 — `none` (ни одно имя не достигает объявленного effect-sink, оси «unresolved, не
> пустые»); прогон 2 — `_render_templates` (`serialises-yaml`), правило `reaches-an-effect-sink`
> **Unresolved:** прогон 1 — 1 no-seed, 1 unresolved-terminator-name; прогон 2 — 4 name-defined-more-
> than-once, 10 unresolved-terminator-name. `Owns unread: none` в каждой строке обоих прогонов —
> конфиг и деплой команда не видит (см. «Не выведено»).

| Axis | Node | Sites | Owns unread | In scope | Why |
|---|---|---|---|---|---|
| callers (1) | `llm` | 2 — `infrastructure/llm/fallback_provider.py:94` | none | **yes** | дублёр-обёртка должна докладывать монитору исход primary и дублёра по отдельности (владелец должен знать, что ключ облака мёртв, даже когда дублёр держит) |
| callers (1) | `router` | 1 — `application/router/llm_router.py:274` | none | **yes** | `should_fall_back` (401/403 → availability), `_rescue_tier` докладывает монитору; монитор живёт здесь |
| branches (1) | `router` | `should_fall_back` 2/2, `_is_availability_status` 0/1, `_rescue_tier` 4/3 | none | **yes** | меняемые ветки политики и спасения |
| branches (1) | `llm` | `complete` 2/4, `complete_with_tools` 2/3 | none | **yes** | точки доклада исхода |
| co-writers (2) | `social` | 1 — `social/usecases/run_genesis.py:139` | none | no | пишет YAML genesis; к здоровью провайдера не относится |
| callers (2) | `usecases` | 11 — `application/usecases/essential_runner.py:70` | none | **yes** | `OutageNotifier`-порт и `EssentialRunner` — существующий путь «не могу думать»; heartbeat-тики (`usecases/heartbeat.py`) — объект гейта |
| callers (2) | `runtime` | 2 — `runtime/composition.py:289` | none | **yes** | сборка монитора, адаптера сигнала, гейта дорожек (`wiring/proactivity.py`), прокидка health-reader в MultiBot (`wiring/telegram.py`) |
| callers (2) | `telegram` | 1 — `infrastructure/telegram/guppi.py:446` | none | **yes** | `/status` GUPPI, адаптер сигнала владельцу (по образцу `restart_notifier.py`), `MultiBotGateway._build_guppi` |
| callers (2) | `memory` | 4 — `memory/adapters/ollama_reranker.py:137` | none | **yes** | роль в изменении — не реранкер, а автобиография: `SelfActionKind` + `_content_for` для эпизода о простое (`memory/self_action.py:50,128-169`) |
| callers (2) | `llm` | 1 — `infrastructure/llm/fallback_provider.py:158` | none | **yes** | см. выше |
| callers (2) | `personality` | 8 — `personality/adapters/reaction_judge.py:50` | none | yes | с 2026-10-21 (D13): изначально «no — через роутер»; T (S5) показала, что `UpdateMoodFromText._classify_sentiment` роняет ход при мёртвом Tier-0 — узел получает шов `run_optional` (решение координатора по находке теста; расширение осей объявлено владельцу в отчёте 2026-10-21 — возражений на момент R2 не получено) |
| callers (2) | `conversation` | 6 — `conversation/adapters/interim_line.py:46` | none | no | то же |
| callers (2) | `proactivity` | 4 — `proactivity/usecases/detect_patterns.py:173` | none | no | то же; порт `RestartNotifier` (`announce_restart.py:55-64`) не переиспользуется — он про рестарт, своя семантика |
| callers (2) | `coding` | 4 — `coding/usecases/classify_coding_intent.py:55` | none | no | через роутер |
| callers (2) | `capabilities` | 1 — `capabilities/adapters/web/http_url_reader.py:323` | none | no | `ToolLoop.complete_with_tools` мимо роутера (`tool_loop.py:177`) — докладывает обёртка на уровне провайдера (ревью M1: Tier-1 в ToolLoop шёл голым — F1 оборачивает Tier-1 той же обёрткой в `factory`/`wiring/access`, узел `capabilities` не правится) |
| callers (2) | `presence` | 1 — `presence/adapters/staleness_judge.py:47` | none | yes | с 2026-10-21 (D13): изначально «no»; при мёртвом Tier-0 `LlmStalenessJudge` терял уже составленный ответ — `StalenessJudge.assess` → `None`, узел на шве `run_optional` (та же находка) |
| callers (2) | `social` | 3 — `social/adapters/disclosure_consent_judge.py:48` | none | no | через роутер |
| branches (2) | `router` | `run` 1/3, `_rescue_tier` 0/3, `_provider_for` 0/2, `_complete` 1/2 | none | **yes** | инструментирование исходов |
| branches (2) | `usecases` | `_reflect` 1/1, `_reappraised` 1/2, `_evolve` 1/1, `run` ×11 | none | **yes** | тики под гейтом; логика тиков не меняется |
| branches (2) | `runtime` | `startup` 3/1, `main` 1/0 | none | **yes** | сборка |
| branches (2) | остальные узлы | personality / proactivity / conversation / memory / coding / social / telegram `_goal_plan` / presence / capabilities / llm `__init__` | none | no | не меняются |

**Не выведено** (`Owns unread: none` — команда читает только Python в `src/bob`, а изменение достаёт
до файлов вне её поля зрения; каждый ниже — рабочий сайт этой работы, а не «blast radius»):
`kernel` — новое чистое ядро `kernel/provider_health.py` и порты в `kernel/ports.py:114` (узел не всплыл
ни в одном прогоне, потому что seed-файлы в него не ходят); `runtime-app` — `application/runtime/
heartbeat.py:60-87` (гейт тика); `config` — `infrastructure/config/loader.py:63-93, 652-681` (блок
`llm.health`, списки из env); `config/bob.vps.example.yaml` → трекаемый `config/bob.vps.yaml`;
`.github/workflows/deploy-bob.yml:66-87`; `deploy/RUNBOOK.md`; `.gitignore:58-62`. Проверка
`max_symbols` 9.0.0 на существующем индексе (не чистом): находок нет.

## Proposed Solution

### Approach

```
                      исход каждого вызова (success / failure + класс)
  LLMRouter.run ──────────────┐                 ┌──── FallbackLLMProvider.complete
  (tier N, door)              ▼                 ▼      (primary отдельно, understudy отдельно)
                    HealthObserver (порт, kernel/ports.py)
                              │
                 ProviderHealthMonitor (application/router/health_monitor.py)
                   per-provider state = kernel/provider_health.py (чистое ядро)
                              │ переходы: DEGRADED · REMINDER · RECOVERED
            ┌─────────────────┼─────────────────────┬──────────────────────┐
            ▼                 ▼                     ▼                      ▼
   OwnerAlertSink        logger (1 строка        HealthReader           SelfActionRecorder
   (kernel/ports.py)      на переход)            → GUPPI /status        → эпизод о простое
   → infrastructure/                              → гейт дорожек          (RECOVERED)
     telegram/owner_alert.py                        heartbeat
     (бот Боба, chat_id=owner_id,
      шаблон от первого лица, без LLM)
```

**Чистое ядро `kernel/provider_health.py`** (stdlib, функции модуля — mutation-цель):

```python
class HealthState(Enum): HEALTHY, DEGRADED
@dataclass(frozen=True, slots=True)
class HealthPolicy: failures_threshold=5; duration_threshold_s=180.0;
                    reminders_s=(600, 3600, 21600, 86400); probe_s=(60, 120, 300)
@dataclass(frozen=True, slots=True)
class ProviderHealth: state; consecutive_failures; failing_since: float|None;
                      failure_class: str|None; alerts_sent: int; last_alert_at: float|None;
                      last_probe_at: float|None
class Transition(Enum): NONE, DEGRADED, REMINDER, RECOVERED

def on_failure(h, *, now, failure_class, policy) -> tuple[ProviderHealth, Transition]
def on_success(h, *, now) -> tuple[ProviderHealth, Transition]      # RECOVERED только из DEGRADED
def probe_due(h, *, now, policy) -> bool                             # HEALTHY → всегда True
def next_probe_interval(h, policy) -> float                          # по схеме probe_s, потолок — последний
def outage_duration(h, *, now) -> float
```

Правила: `DEGRADED` — когда `consecutive_failures ≥ failures_threshold` **или** `now - failing_since ≥
duration_threshold_s` (что раньше), один раз; `REMINDER` — когда `now - last_alert_at ≥
reminders_s[min(alerts_sent-1, len-1)]`; `RECOVERED` — первый успех из `DEGRADED` (из `HEALTHY` с
накопленными, но допороговыми отказами — просто сброс, без сигнала: одиночный 5xx не будит). Политика с
`failures_threshold < 2` отвергается, как у `outage_state` (`poll_outage.py:42-66`).

**Класс отказа** — строка, которую даёт вызывающий слой: `auth` (401/403), `rate` (429), `server`
(5xx/408), `timeout`, `connection`, `shape` (битая форма), `contract` (прочие 4xx). Классификация —
чистая функция `classify_failure(exc) -> str` в `application/router/fallback_policy.py` (там уже
живут `_is_*`, aiohttp разрешён). `should_fall_back` переписывается через неё: дублёр — для
`auth | rate | server | timeout | connection | shape`; `contract` — наружу, как сейчас.

**Монитор `application/router/health_monitor.py`** (`ProviderHealthMonitor`, реализует `HealthObserver`
и `HealthReader`): словарь `provider_id → ProviderHealth`, `clock` (`kernel/ports.py:75`), политика,
`OwnerAlertSink`, `SelfActionRecorder`-колбэк (как `Callable`, чтобы `application` не зависел от
`memory`); на переход — лог одной строкой `LLM health tier0-primary: healthy → degraded (auth, 5
failures, since 06:10:42)` и вызов sink'а; ошибки sink'а глотаются с warning (как `notify_outage`).
`provider_id`: `tier0-primary`, `tier0-understudy`, `tier1`. Снимок: `snapshot() -> Mapping[str,
HealthView]` для `/status`. Сообщения владельцу — модуль `application/router/health_messages.py`,
по-русски, от первого лица, без LLM:

> «Вова, я не могу думать: облако отвечает 403 (авторизация/квота) уже 3 минуты, 5 запросов подряд.
> Дублёра на этой машине нет — я помолчу и буду пробовать раз в минуту, потом реже. Напомню через 10 минут,
> если не пройдёт.»
> «Вернулся: облако ответило. Молчал 9 дней 23 часа (с 1 октября 06:10 по 10 октября 06:42).»

**Инструментирование.** `LLMRouter.run` докладывает исход каждой попытки тира (`llm_router.py:266-312`);
`FallbackLLMProvider.complete/complete_with_tools` докладывает `tier0-primary` и `tier0-understudy`
отдельно (`fallback_provider.py:94-141`), поэтому ключ облака, мёртвый при живом дублёре, тоже даёт
`DEGRADED tier0-primary` с текстом «дублёр держит, но облако мёртво». `ToolLoop` (мимо роутера,
`tool_loop.py:177`) покрывается через обёртку провайдера. Монитор передаётся в оба конструктора как
необязательный параметр (`None` → `NoopHealthObserver`), чтобы существующие тесты и харнесс не менялись.

**Гейт дорожек** (`runtime/wiring/proactivity.py:153-210` + `application/runtime/heartbeat.py`): новая
обёртка `health_gated(tick, *, reader, provider_id, probe)` в `application/runtime/heartbeat.py`: если
`reader` говорит `DEGRADED` и `probe_due` ложно — тик **пропускается без вызова и без лога**; если зонд
должен идти — тик выполняется как зонд, и его отказ логируется одной строкой INFO без стека (монитор
уже всё записал), а успех снимает деградацию через обычный доклад. Зонд — дорожка `inner_monologue`
(Tier-0, 30 с); `reflect`, `proactive`, `pursue_goals` — под гейтом без зонда; `poll`, `mood_drift` —
не трогаем. Деградация `tier1` гейтит `reflect` (реаппрейзал) только в части Tier-1-шага — остальное
пропускает дверь роутера штатно; это ограничение названо в докстринге.

**Статус GUPPI** (`guppi.py:188, 362-363`): `/status` показывает `_STATUS_TEXT` + снимок: `LLM: tier0
облако — деградирован с 2026-10-01 06:10 (auth, 5 подряд) · дублёр — нет · tier1 — ок`. `HealthReader`
прокидывается `wiring/telegram.py:52-124 → MultiBotGateway → _build_guppi (multibot.py:383-412) →
GuppiHandler(...)` как необязательный параметр.

**Автобиография** (`memory/self_action.py:50, 128-169`): `SelfActionKind.OUTAGE_RECOVERED`, `detail`
несёт `since/until/failure_class/provider`; `_content_for` даёт «Я молчал с 1 по 10 октября: облако
отвечало 403, думать было нечем. Теперь снова могу.» Пишется на `RECOVERED` через колбэк из монитора
(`build_self_action_recorder`, `wiring/self_action.py:38-52`, NoOp без `memory.autobiography`).

**Конфиг и деплой (G5).**
1. Трекаемый `config/bob.vps.yaml` — полный конфиг прода **без секретов и идентификаторов**: токены,
   ключи, `chat_id`, `owner_id`, `allowed_chat_ids`, `bob.topic_id`, `owner_dm_chat_id` — из
   `/opt/bob/.env` как `BOB_TELEGRAM__CHAT_ID=…` (синтаксис `loader.py:40-41, 652-681`). Лоадер
   учится приводить env-значения к типу дефолта (`int`, `bool`, список `int` через запятую) — сейчас
   «values arrive as strings» (`:681`), для `allowed_chat_ids` это блокер.
2. Деплой (`deploy-bob.yml` после `checkout`): `cp config/bob.vps.yaml config/bob.yaml` под `bob`;
   `sha256sum` обоих печатается в лог деплоя и сравнивается (гард «эффективный конфиг = репозиторий»);
   если в трекаемом конфиге `llm.tier0_fallback: ollama` — `ollama pull <tier0_fallback_model>`
   с проверкой `ollama list`, отказ = красный деплой. `.env` по-прежнему не трогается.
3. Старт Боба: `report_tool_health`-подобный отчёт (`wiring/tool_health.py:103`) печатает одной строкой
   состояние дублёра (`включён/модель есть` · `включён/модели нет → сигнал владельцу при старте, Боб
   стартует без дублёра` · `выключен`). Sign-on без дублёра при включённом конфиге — через тот же
   `OwnerAlertSink`.
4. Миграция VPS (разовая, в выкатке BOB-118): идентификаторы переезжают из `/opt/bob/config/bob.yaml`
   в `/opt/bob/.env` **руками владельца или координатора с явного «да»** (RUNBOOK шаг); до этого
   деплой с копированием конфига **не запускается** (шаг проверяет наличие `BOB_TELEGRAM__OWNER_ID` в
   `.env` и падает с понятной причиной).

**Spike A — дублёр на VPS** (решение владельца Р1: «C как минимум + spike A»): `ollama pull qwen3:8b`
(≈5 ГБ, диск 69 ГБ свободно) и 5 прогонов через `/v1/chat/completions` с промптами трёх сервисных дверей
(INNER_MONOLOGUE ~1.5 k токенов входа, REFLECT ~2 k, классификатор ~0.5 k). **Критерии включения A:**
REFLECT-ответ (~150 токенов) ≤ 90 с и классификатор ≤ 15 с при одновременно живом `bge-m3`,
RSS Ollama + Боб ≤ 6.5 ГБ. Проходит → `tier0_fallback: ollama` в трекаемом конфиге, модель тянет деплой;
не проходит → в конфиге остаётся выключено с числами замера в комментарии, вариант B (второй облачный
провайдер) — отдельное решение владельца с ответом по приватности §7.1. Spike пишет 5 ГБ на диск VPS
и крутит CPU несколько минут — утверждение этого RFC и есть «да» на эти действия; модель остаётся,
если A принят, иначе `ollama rm`.

### Changes

| File / Module | Change |
|---|---|
| `src/bob/kernel/provider_health.py` | новое чистое ядро: `HealthState`, `HealthPolicy`, `ProviderHealth`, `Transition`, `on_failure/on_success/probe_due/next_probe_interval/outage_duration` — mutation-цель |
| `src/bob/kernel/ports.py` | `HealthObserver` (`record_success(provider_id)`, `record_failure(provider_id, failure_class)`), `HealthReader` (`snapshot()`, `is_degraded(provider_id)`, `probe_due(provider_id)`), `OwnerAlertSink` (`notify_owner(text)`), `HealthView` |
| `src/bob/application/router/fallback_policy.py` | `classify_failure(exc) -> str`; `should_fall_back` через классы; 401/403 → `auth` → дублёр; докстринг-контракт переписан (`:55-57`) |
| `src/bob/application/router/health_monitor.py` | `ProviderHealthMonitor` (observer + reader + переходы → sink/лог/колбэк), `NoopHealthObserver` |
| `src/bob/application/router/health_messages.py` | тексты владельцу (degraded / reminder / recovered / понижен дублёром / дублёр не стартовал), форматирование длительности |
| `src/bob/application/router/llm_router.py` | параметр `health: HealthObserver | None`; доклад исходов в `run`/`_rescue_tier` (`:266-312`); `logger.exception("…no fallback")` (`:311`) → `warning` одной строкой, без стека, когда провайдер уже `DEGRADED` |
| `src/bob/infrastructure/llm/fallback_provider.py` | параметр `health`; доклад `tier0-primary` и `tier0-understudy` отдельно (`:94-141`) |
| `src/bob/infrastructure/llm/factory.py` | прокидка `health` в обёртку; сигнал «дублёр включён, модели нет» на старте |
| `src/bob/infrastructure/telegram/owner_alert.py` | адаптер `OwnerAlertSink` по образцу `restart_notifier.py:27-59` (бот Боба, `chat_id=owner_id`, `_PlainNotifyBot`) |
| `src/bob/infrastructure/telegram/guppi.py`, `multibot.py` | `/status` со снимком здоровья (`:188, 362-363`); `HealthReader` через `_build_guppi` (`:383-412`) |
| `src/bob/application/runtime/heartbeat.py` | `health_gated(tick, *, reader, provider_id, probe)`; `periodic` без изменений семантики |
| `src/bob/application/usecases/heartbeat.py` | без изменения логики тиков; докстринг про гейт |
| `src/bob/runtime/wiring/proactivity.py`, `wiring/telegram.py`, `wiring/self_action.py`, `runtime/composition.py` | сборка монитора (`llm.health`), адаптера, гейтов дорожек (`:153-210`), прокидка reader в MultiBot, колбэк автобиографии |
| `src/bob/memory/self_action.py` | `SelfActionKind.OUTAGE_RECOVERED` + ветка `_content_for` (`:50, :128-169`) |
| `src/bob/infrastructure/config/loader.py` | дефолты `llm.health` (`failures_threshold`, `duration_threshold_seconds`, `reminders_seconds`, `probe_seconds`, `owner_alert`); приведение env-значений к типу дефолта (`:681`) |
| `config/bob.vps.yaml` (новый, трекаемый), `config/bob.vps.example.yaml` (→ указатель), `config/bob.example.yaml` | блок `llm.health`; идентификаторы — только через `.env` |
| `.github/workflows/deploy-bob.yml`, `deploy/RUNBOOK.md`, `deploy/bootstrap.sh` | копирование + sha-гард конфига, `ollama pull` по конфигу, предусловие `.env`; шаги миграции |
| `tests/acceptance/features/llm_health.feature` + steps, `tier0_fallback.feature` (S-new: 401/403) | сценарии PRD по именам; харнесс `tier0_fallback_harness.py` расширяется поведениями `FORBIDDEN(403)`/`UNAUTHORIZED(401)` и фейковым `OwnerAlertSink` |
| `tests/application/router/test_fallback_policy.py:173-177` | 401/403 переезжают из «contract» в «availability»; `classify_failure` параметризован |
| `tests/kernel/test_provider_health.py` | TDD ядра; `pyproject.toml [tool.mutmut].source_paths` += `kernel/provider_health.py` |
| `docs/architecture.md`, `docs/domains/*` (router, llm, telegram, runtime, memory, config), VISION §7.1, Issues #64, ROADMAP | tech-writer |

### API Changes
Публичных API (Telegram-команд) — одно изменение: `/status` GUPPI отвечает снимком здоровья вместо
фиксированной строки. Конфиг: новый блок `llm.health` (все ключи с дефолтами — старые конфиги валидны);
`config/bob.vps.yaml` — новый трекаемый файл. Конструкторы `LLMRouter`, `FallbackLLMProvider`,
`MultiBotGateway`, `GuppiHandler` получают необязательные параметры.

## Alternatives Considered

### Option A: Счётчик внутри `periodic` (heartbeat) без ядра состояния
Проще, но видит только тики, а не вызовы из диалога, и не отличает «облако мёртво, дублёр держит» от
здорового; `/status` и автобиографии взять неоткуда. Отвергнуто.

### Option B: Внешний мониторинг (uptime-пинг, Prometheus/alertmanager)
Честный, но чужой слой: требует ещё одного сервиса и не даёт Бобу знать о себе (G4) — PRD non-goal.

### Option C: Переиспользовать `RestartNotifier`/`AnnounceRestart`
Порт в `proactivity`, семантика «рестарт», таймаут и формулировка под него; растягивать его — смешение
ответственностей (Cohesion). Берём образец адаптера, не порт.

### Option D: 401/403 → retry в `is_transient`
Долбить мёртвый ключ ретраями — ровно то, от чего уходим; 403 остаётся не-transient для retry и
становится availability для **маршрутизации** и **здоровья**. Разные вопросы — разные ответы.

## Risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Сигнал владельцу шлётся через тот же Telegram, который может быть недоступен | Low | Med | Non-goal PRD; переходы всегда в логе; `/status` покажет при первом же обращении |
| Шумные сигналы по ночам (одиночные 5xx) | Low | Med | Пороги 5/180 с по замеру логов (1–4 транзиента/день вне окон 403); сценарий «одиночный 503 сигнала не даёт» |
| Гейт дорожек спрячет не-LLM ошибки тика (БД) | Med | Med | Гейт пропускает тик только по состоянию провайдера; прочие исключения идут как раньше в `periodic`; тест «ошибка БД в degraded логируется стеком» |
| `allowed_chat_ids` из env — список | High (сейчас строка) | High | приведение по типу дефолта + тест на реальном `ConfigLoader(env=…)` (харнесс уже так делает) |
| Публичный репо: утечка id/секрета в трекаемый конфиг | Low | High | гард-тест: `config/bob.vps.yaml` не содержит цифр длиннее 5 подряд в полях `*_id*`/`token`/`key` и не содержит значений этих ключей вовсе |
| Spike A: qwen3:8b на CPU слишком медленный → дублёр остаётся выключен | Med | Med | критерии названы заранее; C (сигнал+зонд+статус) закрывает #64 независимо; B — отдельное решение |
| Деплой с `cp` конфига до миграции id в `.env` сломает прод | Med | High | предусловие в шаге деплоя (`BOB_TELEGRAM__OWNER_ID` в `.env`), иначе красный до рестарта |
| Монитор-доклад из `FallbackLLMProvider` и из роутера даёт двойной учёт одного вызова | Med | Low | provider_id разные (`tier0-primary`/`tier0-understudy` из обёртки, `tier1` из роутера); роутер докладывает только `tier1` и «tier0 без обёртки» — тест на харнессе: число записей = число HTTP-вызовов |

## Open Questions

| # | Question | Decision |
|---|---|---|
| Q1 | Дублёр на VPS — домен отказа (PRD Р1) | Decided: C как минимум + spike A по критериям выше; B — отдельное решение (владелец, 2026-10-21 «утверждаю» PRD с рекомендациями). **Spike A (D9, 2026-10-21): отклонён** — REFLECT 116 с холодный / 76 тёплый (порог 90), классификатор 39 / 4 (порог 15), `qwen3:8b` 5,9 ГБ + `bge-m3` 1,2 ГБ > 5,8 ГБ доступных → взаимное вытеснение; `tier0_fallback` на VPS выключен, модель снята. Дальше: B или замер `qwen3:4b` — решение владельца |
| Q2 | Канал сигнала (PRD Р2) | Decided: бот Боба, личка `owner_id`, шаблон от первого лица без LLM; GUPPI — `/status` |
| Q3 | Пороги (PRD Р3) | Decided по порядку величин, дефолты: 5 отказов / 180 с; напоминания 600/3600/21600/86400 с; зонд 60/120/300 с — конфиг `llm.health` |
| Q4 | Нужен ли сигнал при `DEGRADED tier0-primary`, когда дублёр держит | Decided: да, с текстом «дублёр держит» — ключ облака надо чинить, пока дублёр жив |
| Q5 | `memory.autobiography` на VPS — включён ли (эпизод о простое пишется только при нём) | Decided 2026-10-21: на VPS `true` (прочитано при spike D9); значение в трекаемом `config/bob.vps.yaml` (F4) |
| Q6 | Живой смоук (порча ключа Tier-0 на VPS) — кто и когда | Decided 2026-10-21: при выкатке BOB-118, процедура `deploy/RUNBOOK.md` §10 (ключ — §10.1; восстановление — §10.2 через iptables по uid `bob`, режет оба тира), каждое действие — с явным «да» владельца; до фикса DM-уведомления (отдельная беада) смоук из темы группы; результат — в ACTIVE BOB-116 «Results» |

## Реализация: отклонения от RFC (2026-10-21)

Текст выше — утверждённый замысел, он не переписан. Ниже — где реализация разошлась с ним и
почему; подробности — в беадах `bob-i83.*`.

| Где | В RFC | В коде | Почему |
|---|---|---|---|
| Ядро | `ProviderHealth` без счётчика зондов | поле `failed_probes` — индекс расписания зонда (D1) | число отказов не годится: `DEGRADED` по длительности наступает при числе меньше порога |
| Тесты ядра | `tests/kernel/test_provider_health.py` | `tests/domain/kernel/test_provider_health.py` (D1) | mutmut отбирает тесты из `tests/domain`; в `tests/kernel` гейт был бы фантомным |
| Автобиография | факты простоя в `detail` | типизированное поле `SelfAction.outage: OutageSpan` (D7) | `detail` у других видов выводится в текст дословно, упаковка в строку потребовала бы разбора обратно |
| `health_gated` | `(tick, *, reader, provider_id, probe)` с часами | без часов (их держит монитор), плюс `gate_id` (D5, F2) | `probe_due` уже отвечает «пора ли»; `gate_id` разводит «закрыта ли дорожка» и «чей зонд» |
| Гейт дорожек | по состоянию `tier0-primary` | по `TIER0_EFFECTIVE` — облако лежит И дублёра нет, он снят или лежит (F2, ревью M2) | гейт по облаку глушил рефлексию при живом дублёре вопреки US-2 |
| Breaker | гейт дорожек | плюс breaker в композите дублёра: облако трогают только зонды (G1, ревью R2 N1) | после F2 каждый вызов при живом дублёре бил в мёртвое облако — ~2880 вызовов и строк в сутки от одного монолога |
| `ToolLoop` | «покрывается через обёртку провайдера» | обёртка `ReportingLLMProvider` на Tier-1 в фабрике (F1, ревью M1) | до F1 обёртка стояла только на Tier-0, и 401/403/5xx Tier-1 на ходе владельца не видел никто |
| Русские слова | форматирование в `health_messages` | `kernel/ru_text.py` — один дом для сообщения владельцу, эпизода и `/status`; `kernel/local_time.py` — один пояс (F3, D11, D12) | три копии уже разошлись («со 2 октября» против «с 2 октября»), а время говорилось в двух поясах |
| Ход | сервисные двери Tier-0 возвращают `None` | `LLMRouter.run_optional` для настроения и пересмотра черновика (D13) | 403 на классификаторе настроения ронял ход раньше уведомления GUPPI (S5) |
| Дублёр при старте | сигнал «модели нет», Боб стартует без дублёра | плюс снятие дублёра на роутере и в мониторе до перезапуска (D11) | в D10 провайдеры не пересобирались: обёртка оставалась, монитор считал дублёр подключённым, и до порога отказов дублёра простой облака читался как «держусь на дублёре», а не как немота |
| Тексты | «Вернулся: … Молчал 9 дней 23 часа (с 1 октября 06:10 по 10 октября 06:42)» | «Вова, я вернулся: облако ответило. Молчал 32 минуты (1 октября с 06:10 до 06:42 +03:00)» (D3, D11, G2) | в примере RFC арифметическая ошибка (на деле 9 дней 32 минуты); время подписано смещением; часы — «с … до …» |
| `VOICE_DOWN` | текст не описан; первая версия (D3) — «Говорить в полную силу я сейчас не могу» | «Тебе и команде я сейчас ответить не могу — вместо меня GUPPI пишет, что я недоступен» (G2, ревью R2 N2) | на пути владельца (`ToolLoop`) отступления на Tier-0 нет, первая версия обещала то, чего нет |

Spike A (Q1) отклонён замером — числа в Q1 выше и в `bd comments bob-i83.5`.
