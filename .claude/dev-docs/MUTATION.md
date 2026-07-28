<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# Инструментарий качества: BDD-acceptance + mutation testing

> Каркас заложен в **BOB-066, Срез 0** (`bob-vol.1.1`). Стоячая методология всего
> репозитория — см. `.claude/CLAUDE.md §0.2`.

Пирамида качества (снаружи-внутрь): **BDD acceptance → mutation gate → TDD unit →
DDD-границы + cohesion**. Этот документ описывает два верхних слоя как инструменты.

---

## 1. BDD acceptance (pytest-bdd + Gherkin)

Наблюдаемое поведение Боба — **через границу** (fake-gateway), а не по внутреннему
состоянию: ответ / реакция / молчание / честный нотис об аварии.

```
tests/acceptance/
├── features/            # .feature на русском (живая документация для owner)
├── steps/               # step-definitions (собираются как pytest-тесты)
├── conftest.py          # фикстура scenario_context (изолированный temp db + soul)
└── fake_gateway.py      # общий харнесс: FakeGateway (граница) + run_turn (весь граф на фейках)
```

- **`FakeGateway`** — фейковый aiogram-бот, записывает всё, что Боб испускает
  (`sent` реплики, `reactions`, `typings`). Шаги ассертят ТОЛЬКО это.
- **`run_turn(tmp_path, text=…, reply=…)`** — поднимает весь GUPPI-граф на фейках
  (captured LLM-провайдеры, без сети, temp SQLite) и прогоняет один входящий ход.
- Сценарии — синхронные (pytest-bdd генерит sync-тест); async-ход гоняется через
  `asyncio.run` внутри шага When.

Запуск: `uv run pytest tests/acceptance/`. Эталон — `direct_address.feature`
(прямое обращение → реплика), проверяет проводку end-to-end. Следующие срезы
добавляют INV-1…9 + сценарии PRD A/B/C/D на том же харнессе.

---

## 2. Mutation testing (mutmut) — прицельно на чистых ядрах

Mutation измеряет **силу** тестов: вносит мутацию (перевёрнутое сравнение, off-by-one,
подменённая константа) и требует, чтобы тест **упал** (убил мутанта). Выживший мутант =
тест исполнил строку, но ничего про неё не утверждает.

### Что в scope, что нет

- **В scope (мутируется):** чистая доменная логика вердиктов/политик/порогов —
  `conversation`, `social`, `personality`, `memory`, `proactivity`, `coding`,
  `capabilities` (детерминированные ядра). Конфиг — `[tool.mutmut]` в `pyproject.toml`
  (`source_paths`).
- **НЕ в scope (исключено):** адаптеры (`*/adapters/*`), порты (`*/ports.py`),
  re-export `__init__`, а также технические слои `application` / `infrastructure` /
  `runtime` / `kernel` (не перечислены в `source_paths`). Причина: I/O, LLM, async,
  gateway медленны, недетерминированы и неинформативны для mutation.
- Coverage-stats фаза гоняет только быстрый **`tests/domain/`** (чистые unit-тесты),
  а не медленный async e2e/integration-набор.

### Как гонять (per-срез, вручную)

```bash
scripts/mutation.sh social.sulk           # мутировать только src/bob/social/sulk.py
scripts/mutation.sh conversation.brevity  # другой модуль
scripts/mutation.sh                        # вся чистая доменная поверхность (медленно)
```

Аргумент — dotted-суффикс модуля; скрипт оборачивает его в glob и передаёт mutmut как
фильтр имён мутантов, так что реально прогоняются только мутанты этого модуля.

### Порог и честность

- **Порог: mutation-score ≥ 85%** на затронутом domain-модуле (или «0 выживших в
  core-verdict»).
- **Эквивалентные мутанты** (семантически неотличимые — напр. подмена константы, которую
  ни один контракт не фиксирует) — **явный триаж-игнор в комментарии беада**, НЕ подгонка
  цифры. Подогнанный балл = ложь: убей мутанта или честно задокументируй эквивалентность.

### Эталонный baseline (Срез 0)

Прогон `scripts/mutation.sh social.sulk` на `src/bob/social/sulk.py` (чистое
обида/охлаждение-ядро, tested by `tests/domain/personality/test_sulk.py`):

```
70 мутантов · 🎉 56 убито · 🙁 14 выжило → score 80%
```

Baseline (80%) НИЖЕ порога 85% — это честный сигнал: 14 выживших — граничные (`<=`→`<`
на `critical_warmth` / `exit_intensity`), арифметические (`*`→`/` в warmth-decay) и
default-arg мутанты. Их усиление тестов — работа test-волны (`bob-vol.1.2`
«harness зелёный + порог»); харнесс же доказан рабочим и производит actionable-мутантов.

---

## 3. CI-решение (сознательное)

- **BDD acceptance** — часть `uv run pytest`, гоняется всегда (быстро, детерминированно).
- **Mutation — НЕ в pre-commit / pre-push / `beadloom ci`** (дорого). Это **умышленный
  per-срез ручной прогон** на затронутом domain-модуле. `mutants/` git-ignored.
