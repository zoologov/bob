<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# config — слоёная загрузка конфигурации

Адаптер конфигурации: слоёная загрузка эффективной конфигурации запущенного процесса —
defaults → YAML-файл → окружение. Узел `config` (`part_of` слоя `bob-infrastructure`,
source `src/bob/infrastructure/config/`). Двухботовый layered-loader: значения из
окружения переопределяют YAML, а YAML — встроенные дефолты.

## Спецификация

### Модули

- **loader.py** — `ConfigLoader`, сборка эффективной конфигурации из трёх слоёв:
  встроенные дефолты (`DEFAULT_CONFIG`), опциональный YAML-файл и окружение (`load()`);
  окружение имеет наивысший приоритет, дефолты — низший. Переменная `BOB_<секция>__<ключ>`
  кладётся по пути `<секция>.<ключ>` (двойное подчёркивание — вложенность); токены ботов
  и ключи API отображаются отдельной таблицей (`_TOKEN_ENV_MAPPING`).
- **env_coercion.py** (BOB-116 D8a) — `coerce_env_value(env_key, path, raw, *, defaults,
  list_element_types)`: env-строка получает ТИП встроенного дефолта по тому же пути. До
  BOB-116 значения из окружения приходили строками, и каждый читатель угадывал тип сам;
  `runtime/config._int` принимал только `str.isdigit`, поэтому отрицательный id группы из
  env становился дефолтом `0`. Порядок проверки — `bool` раньше `int` (`bool` — подкласс
  `int`):
  - `bool` — `true/false`, `1/0`, `yes/no`, `on/off` без учёта регистра;
  - `int` — целый литерал (дробь отвергается, а не усекается);
  - `float` — любой литерал с плавающей точкой;
  - список — элементы через запятую, каждый приводится к типу элементов дефолта; у пустого
    дефолта тип объявлен в `loader._LIST_ELEMENT_TYPES` (сейчас `telegram.allowed_chat_ids`
    → `int`), иначе `str`; пустое значение — пустой список, пустой элемент — ошибка;
  - строковый дефолт и путь без дефолта — сырая строка, как раньше.

  Неприводимое значение поднимает `ValueError` с именем переменной и путём: опечатка в
  `.env` останавливает старт, а не превращается в тихий дефолт. Поэтому дефолты таймаутов,
  которые потребитель читает как `float`, объявлены `float` (`llm`, `search`, `read_url`,
  `github`).
- **__init__.py** — фасад пакета (layered configuration loading: defaults → YAML → env).

### Блок `llm.health` (BOB-116)

Пороги монитора здоровья LLM-провайдеров; все ключи с дефолтами, старые конфиги валидны.

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `failures_threshold` | `5` | отказов подряд до «провайдер лёг» (`< 2` отвергается при сборке политики) |
| `duration_threshold_seconds` | `180` | или столько секунд отказов подряд — что наступит раньше |
| `reminders_seconds` | `[600, 3600, 21600, 86400]` | напоминания владельцу; последний интервал повторяется |
| `probe_seconds` | `[60, 120, 300]` | зонд лёгшего провайдера; последний интервал повторяется |
| `owner_alert` | `true` | `false` оставляет строку лога и не шлёт сообщение владельцу |

Читает блок сборка (`runtime/wiring/health.py`, `build_health_policy`), см.
[`services/runtime.md`](../../../../services/runtime.md).

### Конфигурация прода (BOB-116 D8a/D8b)

Трекаемый `config/bob.vps.yaml` — полный конфиг VPS **без секретов и без идентификаторов**:
репозиторий публичный. Идентификаторы чатов, владельца, топика, токены и ключи приходят из
`/opt/bob/.env` (`BOB_TELEGRAM__CHAT_ID`, `BOB_TELEGRAM__OWNER_ID`,
`BOB_TELEGRAM__ALLOWED_CHAT_IDS`, `BOB_TELEGRAM__BOB__TOPIC_ID`, токены и ключи API) и
приводятся к типу по правилу выше. Выкатка (`deploy-bob.yml`) до рестарта проверяет `.env`,
собирает `config/bob.vps.yaml` лоадером Боба с настоящим `.env`, копирует его в
`config/bob.yaml` со сверкой sha256 и тянет модель дублёра, если он включён. Порядок и откат —
`deploy/RUNBOOK.md` §8–§9; инструмент проверки — `deploy/check_config.py`. `config/bob.vps.example.yaml`
стал указателем на трекаемый файл.

## Инварианты

- Порядок слоёв фиксирован: defaults → YAML → env, где каждый следующий слой
  переопределяет предыдущий.
- Значение из окружения имеет тип дефолта по своему пути; неприводимое значение
  останавливает загрузку с именем переменной (BOB-116).
- Трекаемые конфиги (`config/bob.vps.yaml`, `config/bob.example.yaml`) не несут ни
  секретов, ни идентификаторов: это держит гард по числам, похожим на id, при любых
  разделителях между цифрами (`tests/support/id_like_numbers.py`).
- Загрузка конфигурации изолирована в инфраструктуре; домен и use-case'ы получают уже
  разрешённые значения через проводку composition root (`src/bob/runtime/config.py`,
  `wiring/parameters.py`).

## API

Модуль `src/bob/infrastructure/config/loader.py`:
- `ConfigLoader.load()` — построить эффективную конфигурацию из defaults + YAML + env.

Модуль `src/bob/infrastructure/config/env_coercion.py`:
- `coerce_env_value(env_key, path, raw, *, defaults, list_element_types)` → значение типа
  дефолта по `path`; `ValueError` с именем `env_key`, если не приводится.

## Тестирование

Тесты: `tests/infrastructure/config/test_loader.py` (в том числе приведение env по типу
дефолта, списки id из env, блок `llm.health`). Гарды чистоты трекаемых конфигов —
`tests/infrastructure/config/test_vps_config_is_clean.py` и `test_example_config_is_clean.py`
поверх `tests/support/id_like_numbers.py` (`tests/support/test_id_like_numbers.py`: склеиваются
цифры через дефис, точку, пробел, табуляцию, типографские тире и апостроф). Решения прод-конфига
— `tests/deploy/test_vps_config_decisions.py`, проверки выкатки —
`tests/deploy/test_check_config.py` и `test_deploy_workflow.py` (исполняет скрипт выкатки на
фейковом каталоге). Секции конфигурации отдельных фич покрываются `tests/test_*_config.py`
(например `test_search_config.py`, `test_dialogue_config.py`, `test_floor_config.py`).

<!-- beadloom:track=src/bob/infrastructure/config/loader.py -->
<!-- beadloom:track=src/bob/infrastructure/config/env_coercion.py -->
