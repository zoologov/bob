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

### Ядра, которые уже стоят под гейтом (гонять при касании)

| Цель | Что за ядро |
|------|-------------|
| `interactive.argv_policy` | `build_interactive_argv` / `extract_session_id` — чем параметризуется живой claude (BOB-087.D1/D4b; переехал из `coding.` в E) |
| `coding.sandbox_policy` | `allowed_modes` / `is_allowed_mode` / `extra_dir_argv` / `is_safe_argv_value` — owner-ослабления изоляции (BOB-087.D2) |
| `interactive.resume_policy` | `select_resumable` / `is_confirmation_fresh` — что и когда можно поднять (BOB-087.D3; переехал из `coding.` в E) |
| `coding.naming` | `worktree_branch` / `workspace_branch` — имя ветки из фразы owner'а (транслит) |
| `interactive.intent` | распознавание `/code -i` / `/workspace` / `/resume` / `stop` (бывший `coding.interactive_intent`) |
| `interactive.resume_negotiation` | висящий вопрос «поднимаю?»: адресность, TTL, «да»/«нет», снятие (BOB-087.E) |
| `social.sulk` | эталонный baseline Среза 0 (см. ниже) |

🔴 Мутируется ДОМЕННЫЙ модуль, не адаптер: конвенция mutmut исключает `*/adapters/*`,
поэтому argv живого раннера и вынесен в `interactive/argv_policy.py` — иначе гейт был бы
фиктивным (мутанты внутри адаптера просто не создаются).

### Порог и честность

- **Порог: mutation-score ≥ 85%** на затронутом domain-модуле (или «0 выживших в
  core-verdict»).
- **Эквивалентные мутанты** (семантически неотличимые — напр. подмена константы, которую
  ни один контракт не фиксирует) — **явный триаж-игнор в комментарии беада**, НЕ подгонка
  цифры. Подогнанный балл = ложь: убей мутанта или честно задокументируй эквивалентность.

🔴 **Смотри на ЧИСЛО мутантов, а не только на score** (урок BOB-087.E3, `bob-abk.33`).
100% на четырёх мутантах — это не гейт, а фикция: если политика живёт там, куда mutmut не
заглядывает, мутанты на её значениях просто не рождаются. Где mutmut **слеп**:

- **модульные константы** — мутируются только тела функций, `_FLOOR = 500` наверху файла
  неприкосновенен (сдвиг порога на 400 гейт не заметит);
- **внутренности `isinstance(...)` и `len(...)`** — mutmut пропускает эти вызовы вместе со
  всеми потомками (`NEVER_MUTATE_FUNCTION_CALLS`), так что состав кортежа
  `isinstance(e, (A, B, C))` не мутируется вообще.

Как писать чистое ядро, чтобы гейт был настоящим: **значения политики — в тело функции**
(можно локальной именованной переменной: `server_error_floor = 500` и мутируется, и
читается), а **набор/реестр** — не одним merged-`isinstance`, а по предикату на элемент
(`_is_connection_failure(e) or …`): вызов предиката mutmut нейтрализует (`(None)`), и
выпадение элемента становится видимым мутантом. Проверка честности после рефактора —
рост числа мутантов, а не только цифра score (в `fallback_policy` 4 → 15).

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
