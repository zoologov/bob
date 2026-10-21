<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-116 — Здоровье LLM-стека: состояние, сигнал владельцу, зонд, выкатка

> **Status:** Done
> **Created:** 2026-10-21
> **Last updated:** 2026-10-21 (TW — работа завершена)

---

## Goal

Отказ LLM-провайдера перестаёт быть беззвучной немотой: у Боба есть состояние здоровья провайдеров,
владелец получает личное сообщение в пределах порога и «восстановился», heartbeat зондирует мёртвого
провайдера с backoff вместо 30-секундного долбления, 401/403 ведут на дублёра, `/status` показывает
снимок, конфиг прода блока `llm` и дублёр едут выкаткой. Неизменяемо после утверждения.

## Key Constraints

- **Спеки:** [PRD.md](PRD.md) (Approved), [RFC.md](RFC.md) (Approved) — источник намерения; беада `bob-i83` —
  состояние. Решения владельца Р1/Р2/Р3 — в RFC «Open Questions» Q1–Q4 (Decided).
- `kernel` — только stdlib/`typing` (`kernel-no-*`); `application/**` не импортирует `infrastructure/**`;
  порты наблюдателя/читателя/сигнала — в `kernel/ports.py`; классификация aiohttp-ошибок — в
  `application/router/fallback_policy.py`, не в ядре.
- Приватность голоса VISION §7.1 не меняется: `who_may_answer_for_bob` как есть; существующие
  `tier0_fallback.feature` и `voice_that_stays.feature` остаются зелёными без изменения смысла.
- Репозиторий публичный: трекаемый `config/bob.vps.yaml` — без секретов **и без идентификаторов**
  (id, токены, ключи — только `/opt/bob/.env`); гард-тест на это.
- Мutation-цели — функции модуля (`kernel/provider_health.py`, `fallback_policy.classify_failure`),
  не методы `@dataclass`; порог ≥ 85 % с числом мутантов и поимённым триажем.
- Спека ↔ код: инструменты как в CI — `uvx --from beadloom==9.0.0 beadloom …`; гейты на чистом индексе
  (`rm -f .beadloom/beadloom.db`), П.0.3. VPS — только чтение, кроме spike A (`ollama pull qwen3:8b`,
  разрешён утверждением RFC) и миграции id в `.env` при выкатке BOB-118 (отдельное явное «да»).
- Пороги по умолчанию (`llm.health`): 5 отказов / 180 с; напоминания 600/3600/21600/86400 с;
  зонд 60/120/300 с; `owner_alert: true`. Политика с `failures_threshold < 2` отвергается.
- Идентификаторы провайдеров: `tier0-primary`, `tier0-understudy`, `tier1`. Классы отказа: `auth`
  (401/403), `rate` (429), `server` (5xx/408), `timeout`, `connection`, `shape`, `contract` (прочие 4xx).
  Дублёр — для всех, кроме `contract`; `retry.is_transient` не меняется (403 не ретраится).
- Один файл — один агент в волне (П.0.3 п.9); саботаж снимать точечной правкой.

## Code Standards

### Language and Environment
- Python ≥ 3.12, asyncio; aiogram 3.x; SQLite + FTS5; `uv`.

### Methodologies

| Methodology | Application |
|---|---|
| TDD | Red → Green → Refactor; тест-first на ядро и политику |
| BDD | `tests/acceptance/features/llm_health.feature` (+ сценарии 401/403 в `tier0_fallback.feature`), `# language: ru`, имена сценариев — как в PRD; ассерты через границу (loopback-сервер, фейковый `OwnerAlertSink`), не приватное состояние |
| Mutation | `scripts/mutation.sh kernel.provider_health`, `application.router.fallback_policy` — ≥ 85 %, число мутантов и триаж в комментарии беады |
| DDD | DDD-вертикали + shared kernel; порядок слоёв runtime > infra > application > domain; `docs/architecture.md` (BOB-113) |
| Clean Code | SRP (монитор — состояние и переходы; адаптер — только транспорт; сообщения — отдельный модуль), DRY, KISS |

### Testing
- **Framework:** pytest + pytest-cov + pytest-bdd; тесты на транспорт — на настоящем aiohttp loopback
  (харнесс `tests/acceptance/tier0_fallback_harness.py`), не на фейке (П.0.3 п.4).
- **Coverage:** ≥ 80 % на новых модулях; кусачесть каждого нового теста доказана саботажем с именами.

### Code Quality
- `uv run ruff check src/ tests/` · `uv run mypy src/` (strict) · 🔴 `ruff format` на дереве не гонять (П.7).

### Restrictions
- Без `Any`/`# type: ignore` без причины; без `print`; без bare `except`; без `import *`; без мутабельных
  дефолтов; `pathlib`; `yaml.safe_load`; обратные кавычки в shell-строках — только через файл (П.0.3 п.11).

## Architectural Decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-10-21 | Ядро состояния — в `kernel`, порты — в `kernel/ports.py` | единственное место, видимое и `application`, и `infrastructure` без нарушения `application-no-infra`; прецедент `poll_backoff`/`poll_outage` |
| 2026-10-21 | Исходы докладывают и роутер (`tier1`), и дублёр-обёртка (`tier0-primary`/`tier0-understudy`) | владелец должен знать о мёртвом ключе облака даже когда дублёр держит; `ToolLoop` ходит мимо роутера |
| 2026-10-21 | 401/403 → класс `auth` → дублёр; для `retry` — не transient | маршрутизация и ретраи — разные вопросы; долбить мёртвый ключ ретраями — то, от чего уходим |
| 2026-10-21 | Сигнал — бот Боба, личка `owner_id`, шаблон от первого лица, без LLM | решение владельца Р2; путь не должен зависеть от того, что сломалось |
| 2026-10-21 | Зонд — дорожка `inner_monologue`; `reflect`/`proactive`/`pursue_goals` под гейтом без зонда | 30-секундная Tier-0 дорожка — естественный зонд; гейт по состоянию провайдера, не по классу исключения |
| 2026-10-21 | Новый порт `OwnerAlertSink`, а не `RestartNotifier` | разная семантика (Cohesion); адаптер — по образцу `restart_notifier.py` |
| 2026-10-21 | Трекаемый `config/bob.vps.yaml`, id/секреты — `.env`, лоадер приводит типы | репо публичный; «эффективный конфиг = репозиторий» — гард в деплое по sha |
| 2026-10-21 | Эпизод «я молчал» (`OUTAGE_RECOVERED`) пишется **только** когда Бобу действительно было нечем думать: `tier0-primary` деградирован **и** дублёра нет или он тоже деградирован, либо деградирован `tier1` (голос). Облако мёртво при живом дублёре → сигнал владельцу есть, эпизода нет | ложная память хуже дыры; вопрос поднят D7, решение координатора |
| 2026-10-21 | Дублёр на VPS: C (сигнал+зонд+статус+конфиг) обязателен, A — по spike с критериями, B — отдельное решение | решение владельца Р1; домен отказа и приватность не выбираются «по умолчанию» |
| 2026-10-21 | D13: побочный шаг хода (настроение, пересмотр черновика) ходит через `LLMRouter.run_optional` — при отказе доступности провайдера шаг пропускается (`None`, одна строка лога, состояние не тронуто), `contract` и ошибки не провайдера пробрасываются | 403 на классификаторе настроения ронял ход раньше голосовой двери (S5); различать «сервис не смог» и «наш дефект» умеет только роутер (`should_fall_back`), а необязательность шага знает только вызывающий; N разрозненных `except Exception` ловили бы и ошибку БД |
| 2026-10-21 | D11: дублёр, включённый, но не готовый при старте, снимается до перезапуска на роутере и в мониторе сразу (`build_understudy_stand_down`); время владельцу, в `/status` и в эпизоде — в поясе процесса со смещением (`kernel/local_time`) | без снятия простой облака читался как «держусь на дублёре»; три места говорили в двух поясах, подписывало одно |
| 2026-10-21 | F1 (ревью M1): Tier-1 из фабрики обёрнут `ReportingLLMProvider` (`tier1`), роутер не докладывает `SelfReportingProvider` | ход владельца идёт через `ToolLoop` мимо роутера, и отказ Tier-1 там не видел никто |
| 2026-10-21 | F2 (ревью M2): дорожки heartbeat гейтятся по `TIER0_EFFECTIVE` — одно правило `_tier0_mute` для гейта, текста владельцу и эпизода; зонд остаётся за `tier0-primary` | гейт по облаку глушил рефлексию при живом дублёре вопреки PRD US-2 |
| 2026-10-21 | F3 (ревью M3): русские формы о простое — один модуль `kernel/ru_text.py` (stdlib), id провайдеров — константы `kernel/provider_health.py` | копии в трёх модулях уже разошлись; `application` не импортирует `memory` |
| 2026-10-21 | G1 (ревью R2 N1): breaker облака — в композите дублёра (читает `HealthReader`), а не в дорожках; `TIER0_EFFECTIVE` — в ядре и в контракте `HealthReader` | после F2 каждый вызов при живом дублёре бил в мёртвое облако; новый метод порта отклонён — `isinstance(health, HealthReader)` молча отключил бы читатель у чужих фейков |
| 2026-10-21 | G2 (ревью R2 N2): текст `VOICE_DOWN` говорит, что владельцу и команде Боб ответить не может, а гостям отвечает облаком попроще; отступление `ToolLoop` на Tier-0 — решение владельца, не этой работы | прежний текст обещал «слабее, но говорю», а на пути владельца отступления нет |
| 2026-10-21 | Mutation-гейт — `scripts/mutation.sh`, прогоны строго по одному; `mutation.targets` в `.beadloom/flow.yml` не задан | каталог `mutants/` общий, параллельные прогоны портят друг друга (D1/D2); `beadloom mutation` 9.0.0 без целей ничего не меряет |

## Related Files

Открывать через `uvx --from beadloom==9.0.0 beadloom ctx <ref>`: `router`, `llm`, `kernel`, `runtime`,
`runtime-app`, `telegram`, `config`, `memory`, `bob-application`. Таблица изменений — RFC «Changes».

## Current Phase

- **Phase:** Done (2026-10-21) — все беады `bob-i83.1…24` закрыты, итоги — в [ACTIVE.md](ACTIVE.md)
  «Results».
- **Current bead:** —
- **Blockers:** none. Вне этой работы: выкатка тегом BOB-118 (`bob-sgm`) с миграцией RUNBOOK §9 и
  живым смоуком §10; решение владельца по дублёру на VPS (вариант B или замер `qwen3:4b`).
