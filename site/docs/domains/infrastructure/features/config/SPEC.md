<!-- beadloom:badge-start -->
> ✅ **fresh**
> 
> last synced 2026-10-21T08:49:35.850635+00:00 · coverage 100% (`config`)
> 
> _Validation by Beadloom `doc_sync` — same source as `sync-check`._
<!-- beadloom:badge-end -->

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
  встроенные дефолты, опциональный YAML-файл и окружение (`load()`); окружение имеет
  наивысший приоритет, дефолты — низший.
- **__init__.py** — фасад пакета (layered configuration loading: defaults → YAML → env).

## Инварианты

- Порядок слоёв фиксирован: defaults → YAML → env, где каждый следующий слой
  переопределяет предыдущий.
- Загрузка конфигурации изолирована в инфраструктуре; домен и use-case'ы получают уже
  разрешённые значения через проводку composition root (`src/bob/runtime/config.py`,
  `wiring/parameters.py`).

## API

Модуль `src/bob/infrastructure/config/loader.py`:
- `ConfigLoader.load()` — построить эффективную конфигурацию из defaults + YAML + env.

## Тестирование

Тесты: `tests/infrastructure/config/test_loader.py`. Секции конфигурации отдельных фич
покрываются `tests/test_*_config.py` (например `test_search_config.py`,
`test_dialogue_config.py`, `test_floor_config.py`).

<!-- beadloom:track=src/bob/infrastructure/config/loader.py -->
