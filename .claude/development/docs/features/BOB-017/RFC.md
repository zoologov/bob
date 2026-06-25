<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-017 Phase A — «Боб знает свой мир» (read-only самоинтроспекция)

> **Status:** Approved
> **Created:** 2026-06-25
> **Feature:** BOB-017 Phase A · реализует PRD BOB-017 Phase A

---

## Контекст и опора

Capability-шов уже есть (BOB-002): порт `Capability` (`name`/`description`/`input_schema`/
`permission`/`async execute`), `CapabilityRegistry` (advertise→`manifest`, dispatch, `describe`),
`ToolLoop` в `handle_message`. Навыки строятся фабриками `make_*_capability(deps)` и регистрируются
в `_build_registry(...)` (`app.py`), откуда `registry` идёт в `HandleMessage`. Tool-loop включается,
когда registry непустой И провайдер умеет tool-calling. Образец: `recall_memory`/`search_memory`.

Phase A добавляет **read-only навыки самоинтроспекции** за этим же швом — без нового транспорта,
без записи, без исполнения произвольного CLI.

## Решение (обзор)

Три read-only навыка, каждый `permission="safe"`, за существующим швом:

1. **`inspect_architecture`** — обёртка над локальным `beadloom` (`ctx`/`graph`/`why`/`search`):
   архитектурный контекст/граф/импакт/поиск по узлам. Аргумент — `ref_id` или запрос.
2. **`read_code`** — поиск + чтение исходников: glob/grep по `src/`+`tests/` → список совпадений;
   чтение ограниченного фрагмента файла. **Приват-фильтр путей** (см. ниже).
3. **`list_work`** — обёртка над локальным `bd` (`ready`/`show`): состояние трекера задач.

Боб вызывает их в диалоге через tool-loop; GUPPI исполняет (как `recall_memory`). Persona
`describe()` перечисляет их, чтобы Боб знал, что умеет заглянуть в свой мир.

## Архитектура (DDD/Clean)

**Домен (`domain/`) — чистое, без I/O:**
- `domain/introspection/privacy_guard.py` — чистый `PrivacyGuard`: детерминированно решает, можно ли
  читать путь / передавать вывод. **DENY-инвариант** (не обходится промптом): запрещены
  `data/soul/**`, `data/bob.db*`, `.env*`, `config/**`, любой путь вне `src/`+`tests/`+`docs/` репо
  (allowlist-корни). Чистые предикаты `allows_path(p)`/`sanitize(text)` + юнит-тесты.

**Порты (`domain/ports.py`):**
- `RepoIntrospector` (Protocol) с `architecture_context(ref) / search_code(query) / read_file(path,*) /
  list_tasks(query?)` → возвращают строковый/структурный результат. Абстракция, чтобы инфраструктура
  (subprocess/файлы) подменялась фейком в тестах.

**Инфраструктура (`infrastructure/introspection/`):**
- `subprocess_introspector.py` — реализация `RepoIntrospector`: запуск `beadloom`/`bd` через
  `asyncio.create_subprocess_exec` (**не shell**, фикс-allowlist подкоманд — никаких произвольных
  аргументов/записи/инъекций; таймаут; обрезка вывода) + `read_file` через `PrivacyGuard` (путь
  проверяется ДО чтения; вывод санитизируется). Только read-подкоманды.

**Приложение (`application/capabilities/`):**
- `inspect_architecture.py` / `read_code.py` / `list_work.py` — фабрики `make_*_capability(introspector)`
  по образцу `recall_memory.py`: `permission="safe"`, JSON-Schema на 1 аргумент, `execute` делегирует в
  порт и рендерит компактный результат.

**Композиция (`app.py`):**
- В `_build_registry(...)` зарегистрировать три навыка, если `introspection.enabled`. Сконструировать
  `SubprocessRepoIntrospector(PrivacyGuard(repo_root=...), beadloom_bin, bd_bin)`. Пробросить в persona
  `describe()`. Конфиг `introspection.{enabled, ...}` → loader.

## 🔴 Приватность (обязательное требование PRD)

- **`PrivacyGuard` — единственная точка правды**, чистый домен, enforce на инфра-границе ПЕРЕД любым
  чтением/возвратом. DENY: `data/soul/**`, `data/bob.db*`, `.env*`, `config/**`; ALLOW только
  `src/**`, `tests/**`, `docs/**`, граф-метаданные beadloom. Не зависит от промпта/LLM.
- `read_code` физически не может прочитать личные данные (путь отвергается). `inspect_architecture`/
  `list_work` отдают граф/беады (код-метаданные), не «нутро» Боба; вывод проходит `sanitize`.
- Юнит-тесты на инвариант: запросы к SOUL/`bob.db`/`.env`/`config` → отказ, в облако не уходят (US-6).

## Данные и конфиг

- **Нет миграций БД.** Навыки только читают репозиторий/трекер.
- Конфиг `introspection`: `enabled` (дефолт **true** — это и есть фича; read-only, чат owner-only),
  опц. `max_output_chars`, `read_max_lines`, пути бинарей. Phase A **не** добавляет навыки в
  автономный `goals.safe_capabilities` → они только диалоговые, не самонаправленные.

## Тестирование

- `PrivacyGuard` (DENY/ALLOW, обход невозможен); `RepoIntrospector`-фейк для навыков (детерминизм).
- Навыки: верный dispatch, компактный рендер, честный «не нашёл» при пустом (US-5).
- Subprocess-адаптер: фикс-allowlist подкоманд, таймаут, обрезка; путь через guard.
- US-1..6; регрессии: `recall_memory`/`search_memory`/tool-loop целы; пустой registry → как раньше.
- ≥80% покрытие; `.venv/bin/pytest` (uv run висит); `ruff`/`mypy --strict`/`beadloom ci` зелёные.

## Риски и границы

- **Только чтение, фикс-allowlist подкоманд** — нет записи/исполнения CLI/сети (это фазы B/C).
- Граница стадии: навыки **не** в автономном safe-allowlist → tick не может их запускать сам.
- Subprocess к локальным `beadloom`/`bd` — безопасно (локально, read), `exec` без shell.
- Приват-инвариант — единственный «острый» риск, закрыт `PrivacyGuard` + тестами.

## Альтернативы (отвергнуто)

- **In-process вызов beadloom/bd как библиотеки** — лишняя связанность с их внутренностями; subprocess
  стабильнее по контракту (CLI) и проще изолировать.
- **Дать Бобу сырой `read_file`/`shell`** — нарушает приват-инвариант и read-only границу; отвергнуто.
- **LLM-сам-формирует beadloom-команду** — инъекция/запись; берём фикс-allowlist подкоманд.

## Этапы (детализация — в PLAN, беады создаются ПОСЛЕ утверждения PLAN)

1. **dev** — `PrivacyGuard` (домен) + `RepoIntrospector` порт + `SubprocessRepoIntrospector` (инфра) + юнит-тесты.
2. **dev** — три навыка (`inspect_architecture`/`read_code`/`list_work`) + регистрация в `app.py` + persona `describe()` + конфиг.
3. **test** — ≥80% + US-1..6 + приват-инвариант + регрессии.
4. **review** — read-only/приват-инвариант/границы стадии/чистота DDD; read-only.
5. **tech-writer** — `architecture.md` (рус): навыки самоинтроспекции, PrivacyGuard, место в шве. Gate.
