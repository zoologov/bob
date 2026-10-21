<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-10-21T21:04:41.376096+00:00 · coverage 0% (`runtime`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# runtime — composition root + entrypoint

Единственный слой, которому позволено связать сразу все слои и все вертикальные
модули в один работающий процесс GUPPI. `runtime` читает слоёную конфигурацию,
строит реальные адаптеры инфраструктуры, компонует политику приложения и
use-case'ы каждого bounded-context, подписывает обработчики на EventBus,
регистрирует тики и Telegram-поллинг, один раз прогоняет Genesis на первом запуске
и стартует процесс.

До BOB-062.7a composition root жил единым файлом `src/bob/app.py` (2819 строк).
Срез .7a перенёс граф в связный пакет `src/bob/runtime/`, а инлайн-адаптеры
вернул в их доменные дома (`infrastructure/telegram/`, `social/adapters/`,
`coding/adapters/`). `app.py` усох до тонкого re-export shim'а — см. ниже.

## Спецификация

### Раскладка пакета

```
src/bob/runtime/
  __init__.py       # фасад: re-export SystemClock, Application, build_application, _as_dispatch_handler
  composition.py    # build_application() + Application (сама сборка графа — composition root)
  main.py           # main()/_run()/_configure_logging + __main__ (process entrypoint)
  clock.py          # SystemClock + _async_sleep/_monotonic (инжектируемые сеймы времени)
  config.py         # тюнинг-дефолты + config-ридеры (_section/_str/_int/_float/_flag/…) + 🔴 _REPO_ROOT
  wiring/           # внутренний пакет _build_* фабрик (по одной группе на ответственность)
    parameters.py       — чистые config→value ридеры параметров (пороги/частоты/флаги)
    access.py           — _build_authorizer, _as_tool_provider
    telegram.py         — _build_multibot (оба admin-бота за одним MultiBotGateway)
    capabilities.py     — _build_registry, _build_diagram_renderer, _build_introspector
    coding.py           — _build_coding_assistant, _build_coding_router
    permission.py       — _build_permission_flow
    goals.py            — _build_goal_engine, _build_pursue_goals_tick
    self_improvement.py — _build_self_improvement
    memory.py           — _build_consolidate_memory, _build_dedup_facts, _build_embedder, _build_reranker
    proactivity.py      — _build_proactivity_engine, _background_tasks (+ гейт дорожек по здоровью LLM)
    health.py           — монитор здоровья LLM из llm.health, канал сигнала владельцу, снятие дублёра (BOB-116)
    tool_health.py      — report_tool_health, report_understudy (проверка внешних инструментов и дублёра при старте)
    self_action.py      — build_self_action_recorder, build_outage_episode_writer (автобиография)
```

<!-- TODO: verify — раскладка выше перечисляет не все модули `wiring/`: здесь только те, о
     которых говорит этот документ; полный список — каталог `src/bob/runtime/wiring/`. -->


Каждый файл несёт заголовок `# beadloom:domain=bob`, а весь пакет резолвится к узлу
`runtime` (`source: src/bob/runtime/`) с тегом `layer-runtime`.

### Сборка графа (`composition.py`)

`build_application(*, config_path, config, providers, bob_bot, guppi_bot,
embedder, reranker, clock, proactivity_seed) -> Application` — единственный
оркестратор. Все аргументы после `config_path` — инжектируемые сеймы: если не
переданы, реальные адаптеры строятся из конфигурации (токены обоих ботов и
`llm.tier1_api_key` берутся только из env/файлов, никогда не инлайнятся). Тесты
подсовывают фейковые aiogram-боты и фейковый embedder, чтобы прогнать весь граф
без сети и без Telegram-аккаунта.

`Application` — `frozen`-датакласс-результат сборки: держит `runtime`,
`event_bus`, `memory_repo`, `soul_store`, `genesis`, `personality`,
`handle_message`, `intake_dispatcher`, `multibot`, `authorizer`, `registry`, тики
(`inner_monologue_tick`/`mood_drift_tick`/`reflect_tick`/`proactive_tick`) и
опциональные `pursue_goals_tick`/`coding_assistant` (только когда флаг включён).
С BOB-116 ещё `health` (монитор здоровья LLM), `owner_alert` (канал сигнала владельцу) и
`understudy_stand_down` (снятие дублёра на роутере и мониторе сразу); `None` — только в
ручных тестовых сборках.
`startup()` сначала отчитывается о внешних инструментах и о дублёре Tier-0
(`report_tool_health`, `report_understudy` — до инициализации персистентности, Genesis и
любого вызова провайдера), затем инициализирует персистентность, прогоняет идемпотентный
Genesis, загружает soul и резолвит идентичности ботов; `shutdown()` останавливает runtime,
**дренирует intake-диспетчер** (`intake_dispatcher.aclose()` — досдаёт буферизованные
ответы) и закрывает персистентность — именно в этом порядке, чтобы не писать сквозь
закрытое соединение.

### Здоровье LLM (BOB-116, `wiring/health.py`)

Монитор здоровья провайдеров собирается **до** провайдеров и роутера — оба докладывают ему
исход каждого вызова — и **после** рекордера автобиографии, в которую он пишет эпизод «я
молчал». Один и тот же объект `ProviderHealthMonitor` (наблюдатель и читатель) получают:

- фабрика провайдеров (`build_tier_providers(merged, health=monitor)`): Tier 1 обёрнут
  докладывающей обёрткой `tier1`, композит дублёра докладывает облако и дублёр отдельно и
  читает монитор для breaker облака (`domains/infrastructure/features/llm/SPEC.md`);
- `LLMRouter(..., health=monitor)` — доклад вызовов, которые никто другой не докладывает;
- гейт дорожек heartbeat (`_background_tasks(..., health=monitor)`, ниже);
- GUPPI `/status` (`_build_multibot(..., health=monitor)` → `MultiBotGateway` → `GuppiHandler`).

`build_llm_health(config, *, clock, bot, recorder)` → `LlmHealth(monitor, sink)`:

- политика — `build_health_policy` из `llm.health` (дефолты ядра; `failures_threshold < 2`
  останавливает старт `ValueError`). 🔴 Предел, названный ревью (m4): `_seconds` на кривом
  YAML-списке интервалов (`[600, "1h"]`) молча берёт дефолт ядра, тогда как env-путь падает с
  именем переменной;
- канал сигнала — `build_owner_alert_sink`: `OwnerAlert` ботом Боба в личку
  `telegram.owner_id`; `NoopOwnerAlert`, если `llm.health.owner_alert: false` (ключ не задан —
  включён) или `owner_id ≤ 0`. Обращение в тексте — `telegram.owner_name`;
- `has_understudy` — `understudy_endpoint(config) is not None`;
- колбэк восстановления — `wiring/self_action.build_outage_episode_writer(recorder)`: эпизод
  `SelfActionKind.OUTAGE_RECOVERED` с `OutageSpan` во времени пояса процесса, `sender_id=None`,
  `visibility=owner_private`. Без `memory.autobiography` рекордер — no-op. Когда писать эпизод
  (только после настоящей немоты), решает монитор, не сборка.

**Проверка и снятие дублёра при старте (D11).** `Application.startup` первым делом зовёт
`report_tool_health`, затем `wiring/tool_health.report_understudy(config, sink=owner_alert,
stand_down=understudy_stand_down)`: одна строка лога в любом случае (`tier0 understudy: off` /
`on, model … ready` / `on, NOT ready — …`). Если дублёр включён, но не готов, сначала
`build_understudy_stand_down(router=…, monitor=…)` снимает его на роутере
(`stand_down_tier0_understudy`) и в мониторе (`stand_down_understudy(reason)`) — синхронно,
без `await` между ними, — затем владелец получает сообщение «стартовал без дублёра». Боб
стартует в любом случае, без дублёра до следующего перезапуска: модель, скачанная позже, не
подхватывается. Проверка — async HTTP, а `build_application` синхронный, поэтому она живёт в
`startup`, до Genesis и до любого вызова провайдера. Ошибка самой проверки, снятия или
доставки логируется, и старт идёт дальше.

**Гейт дорожек heartbeat (`wiring/proactivity._background_tasks`).** С подключённым
читателем дорожки, которые думают Tier-0, обёрнуты `health_gated(tick, reader=monitor,
provider_id=TIER0_PRIMARY, probe=…, gate_id=TIER0_EFFECTIVE)`:

| Дорожка | Каденция | Под гейтом |
|---|---|---|
| `poll` | непрерывно | нет — LLM не зовёт |
| `inner_monologue` | `heartbeat_seconds` (30 с) | да, это ЗОНД (`probe=True`) |
| `mood_drift` | своя | нет — LLM не зовёт |
| `reflect` | `heartbeat × 10` | да, без зонда |
| `proactive` | `heartbeat × множитель` | да, без зонда |
| `pursue_goals` | `goals.tick_seconds`, только если подключён | да, без зонда |

Дорожка закрывается, только когда Tier-0 целиком не может думать (`TIER0_EFFECTIVE`, F2):
облако лежит И дублёра нет, он снят при старте или лежит тоже. Пока дублёр держит мёртвое
облако, все дорожки идут в своём ритме (PRD US-2), а в облако между зондами не стучится
композит дублёра (breaker, G1). Зонд, его расписание и строка лога — за `tier0-primary`.
Без читателя расписание дорожек такое же, как до BOB-116.

### Entrypoint (`main.py`)

`main(*, config_path=None)` строит приложение, настраивает логирование из
`runtime.log_level` и через `asyncio.run(_run(app))` ведёт жизненный цикл
`startup → runtime.start → run_until_stopped → shutdown`. Блок `__main__`
вызывает `main()`.

### Сеймы времени (`clock.py`)

`SystemClock.now()` — реальный UTC-источник времени, инжектируется в домен, чтобы
тот никогда не звал `datetime.now()` напрямую. Тесты подставляют фиксированные
часы для детерминизма циркадной/governance-логики проактивности и owner-cooldown.

### Конфигурация и `_REPO_ROOT` (`config.py`)

Тюнинг-дефолты процесса (heartbeat/poll/throttle/пороги персональности,
консолидации, дедупа и т.д.) плюс чистые типизированные ридеры секций
(`_section`, `_str`, `_int`, `_int_list`, `_float`, `_float_or`, `_flag`) и
path-ридеры (`_db_path`, `_soul_dir`, `_templates_dir`, `_backfill_name_map`).

🔴 `_REPO_ROOT = Path(__file__).resolve().parents[3]` — после переезда на уровень
глубже (`src/bob/runtime/config.py`) индекс сменился `parents[2] → parents[3]`.
Три использования: `_DEFAULT_TEMPLATES_DIR` и два в `PrivacyGuard`. Промах
резолвил бы корень репозитория неверно и задевал бы `DENY` всего
интроспекшн-дерева, поэтому его корректность закреплена unit-тестом
`_REPO_ROOT == <repo-root>`.

## Инварианты

- **Composition root — единственная точка полного связывания.** Только `runtime`
  импортит все слои и все вертикальные модули. Модули НЕ импортят `runtime`: семь
  правил `*-no-composition-root` в `rules.yml` (BOB-062.7a расширил их globs с
  `src/bob/app.py` на `src/bob/runtime/`), плюс легальное ребро `runtime → все
  модули` и запрещённое `модули → runtime`.
- **🔴 Коллизия имён `runtime` vs `application.runtime`.** `bob.runtime` — это
  composition root / entrypoint. `bob.application.runtime` (узел `runtime-app`,
  `src/bob/application/runtime/`) — это async-примитивы `AgentRuntime` /
  `AsyncEventBus` / `periodic`, которые composition root лишь *стартует*. Это НЕ
  один и тот же модуль; docstring'и каждого файла разводят их явно.
- **Boot-order дословный.** Порядок сборки блоков зафиксирован: `multibot` →
  `sulk_tracker` (`announcer=multibot.guppi`) → `self_improvement`
  (`gateway=multibot.reply_gateway(BOB)`) → proactivity-engine → `pursue_goals` →
  `handle_message`. Комментарии «built AFTER multibot» отмечают зависимости —
  переносить блоками, порядок не тасовать.
- **🔴 Канон о голосе подаётся здесь и только здесь (BOB-096).** Текст запрета
  принадлежит персоне (`personality.voice.guppi_voice_canon`), а вплетают его две
  точки выхода payload'а к модели через порт провайдера — роутер и петля
  инструментов. Связывает их композиционный корень, в трёх местах: сборка
  `LLMRouter`, сборка `HandleMessage` (канон уезжает в его per-turn петлю) и
  `wiring/permission.py` (привилегированное исполнение, идущее мимо роутера).
  Уверенность даёт не то, что аргумент написан: `voice_canon=None` — легальное
  значение типа, и текстовые гарды на нём остаются зелёными. Факт проверяется
  ПОВЕДЕНИЕМ собранного графа —
  `tests/runtime/test_composed_wiring_carries_the_canon.py` строит проводку тем же
  `build_application` и смотрит, что реально доехало до провайдера. Про третью
  провязку сказано честно: разговорная петля получает канон и от персоны тоже
  (`VoiceComposer` вклеивает его в системный промпт без ветвлений), поэтому в живом
  ходе её выключение не меняет ничего — запрет всё равно приезжает персоной. Это
  ремень, который станет несущим в ту секунду, когда персону перепишут, и доказать
  его живым ходом нельзя: нужен payload, который канона не несёт.
- **Shared-instance, не раздваивать.** `_build_registry` возвращает кортеж
  `(registry, diagram_sink, diagram_renderer)` — один `diagram_sink` идёт и в
  `handle_message`, и в capability. `notable_reaction_store` — один kv на
  `handle_message` + `perceive_reaction`. `resolved_bob_bot` — один инстанс всем.
- **Feature-flag off ⇒ None ⇒ inert.** Флаги
  (floor/rule/coding/pursuit/verify/consolidate/dedup/introspection/diagrams/
  search/read_url) при выключении дают `None`-сейм, а не ветку в рантайме:
  выключенная способность инертна, процесс стартует как раньше
  (консервативный дефолт).

## `app.py` — тонкий shim

`src/bob/app.py` больше не composition root, а стабильный re-export фасад
(≈82 строки): он тянет `Application`/`SystemClock`/`build_application` из
`bob.runtime`, `main` из `bob.runtime.main`, `_build_*` фабрики из
`bob.runtime.wiring` и перенесённые инлайн-адаптеры из их новых домов. Это держит
рабочими лаунчер `./bob` (`from bob.app import main` + pgrep-паттерн процесса) и
существующие тесты (`from bob.app import build_application` и `_build_*`), не
трогая их. `main` НЕ ре-экспортится из `bob/runtime/__init__.py` намеренно —
иначе он затенил бы подмодуль `bob.runtime.main`; entrypoint импортится как
`from bob.runtime.main import main`.

## API

Пакет `src/bob/runtime/`:

- `build_application(*, config_path=None, config=None, providers=None, bob_bot=None, guppi_bot=None, embedder=None, reranker=None, clock=None, proactivity_seed=None)` → `Application` — собрать весь двухботовый граф GUPPI из конфигурации.
- `Application` — датакласс-результат сборки; `async startup() -> GenesisResult`, `async shutdown() -> None`.
- `SystemClock` — реальный UTC-источник времени (`now() -> datetime`).
- `main(*, config_path=None) -> None` (`src/bob/runtime/main.py`) — process entrypoint.
- `_as_dispatch_handler` / `_as_reaction_handler` — обёртки под `EventHandler`:
  `_as_dispatch_handler` адаптирует `ChatDispatcher.submit` (быстрый неблокирующий подписчик
  `MESSAGE_RECEIVED`, intake-развязка BOB-066), `_as_reaction_handler` — реакцию.
- `wiring/*` — внутренние `_build_*` фабрики (не публичный контракт; ре-экспортятся для тестов через `app.py`-shim).
- `bob.runtime.wiring.health` (BOB-116): `LlmHealth(monitor, sink)`, `build_llm_health(config,
  *, clock, bot, recorder)`, `build_health_policy`, `build_owner_alert_sink`,
  `build_understudy_stand_down(*, router, monitor)` → `UnderstudyStandDown`,
  `configured_understudy`, `health_owner_name`; `LlmHealth`, `build_llm_health` и
  `build_understudy_stand_down` реэкспортированы из `bob.runtime.wiring`.
- `bob.runtime.wiring.tool_health.report_understudy(config, *, sink, stand_down=None)` →
  `UnderstudyCheck | None` (async).
- `bob.runtime.wiring.self_action.build_outage_episode_writer(recorder)` → `OutageRecovered`.

## Тестирование

Тесты: `tests/test_app.py`, `tests/test_app_hardening.py` и остальные
`tests/test_app_*` (patch-по-атрибуту — `monkeypatch.setattr("bob.runtime.main.asyncio.run", …)`
целится в новый дом entrypoint, а не в shim). Инвариант `_REPO_ROOT` закреплён
unit-тестом `tests/test_runtime_repo_root.py`.

Здоровье LLM (BOB-116): `tests/runtime/test_llm_health_composition.py` (монитор в сборке,
канал сигнала, снятие дублёра), `tests/runtime/test_tool_health_at_startup.py` (строка о
дублёре при старте, сигнал, снятие до первого вызова), `tests/runtime/test_tier1_health_on_the_tool_loop.py`
(обёртка Tier-1 на пути `ToolLoop`), `tests/runtime/wiring/test_health_gated_lanes.py` (гейт
дорожек на настоящем мониторе: при живом дублёре `reflect` идёт в ритме, облако трогают
только зонды), `tests/runtime/wiring/test_outage_episode_writer.py` (эпизод в поясе процесса).
Живая документация — `tests/acceptance/features/llm_health.feature`, вся программа собрана
`build_application`.

<!-- beadloom:track=src/bob/runtime/composition.py -->
<!-- beadloom:track=src/bob/runtime/main.py -->
<!-- beadloom:track=src/bob/runtime/clock.py -->
<!-- beadloom:track=src/bob/runtime/config.py -->
<!-- beadloom:track=src/bob/runtime/wiring/health.py -->

<!-- enrich with: beadloom docs polish -->
