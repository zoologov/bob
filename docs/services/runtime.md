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
  __init__.py       # фасад: re-export SystemClock, Application, build_application, _as_handler
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
    proactivity.py      — _build_proactivity_engine, _background_tasks
```

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
`handle_message`, `multibot`, `authorizer`, `registry`, тики
(`inner_monologue_tick`/`mood_drift_tick`/`reflect_tick`/`proactive_tick`) и
опциональные `pursue_goals_tick`/`coding_assistant` (только когда флаг включён).
`startup()` инициализирует персистентность, прогоняет идемпотентный Genesis,
загружает soul и резолвит идентичности ботов; `shutdown()` останавливает runtime
и закрывает персистентность.

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
- `_as_handler` / `_as_reaction_handler` — обёртки use-case → `EventHandler`.
- `wiring/*` — внутренние `_build_*` фабрики (не публичный контракт; ре-экспортятся для тестов через `app.py`-shim).

## Тестирование

Тесты: `tests/test_app.py`, `tests/test_app_hardening.py` и остальные
`tests/test_app_*` (patch-по-атрибуту — `monkeypatch.setattr("bob.runtime.main.asyncio.run", …)`
целится в новый дом entrypoint, а не в shim). Инвариант `_REPO_ROOT` закреплён
unit-тестом `tests/test_runtime_repo_root.py`.

<!-- beadloom:track=src/bob/runtime/composition.py -->
<!-- beadloom:track=src/bob/runtime/main.py -->
<!-- beadloom:track=src/bob/runtime/clock.py -->
<!-- beadloom:track=src/bob/runtime/config.py -->

<!-- enrich with: beadloom docs polish -->
