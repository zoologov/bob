<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# RFC: BOB-038 — T3.A⁺ «Архитектурный контекст»

> **Status:** Approved
> **Created:** 2026-06-25
> **Feature:** BOB-038 · реализует PRD BOB-038

---

## Контекст и опора (что уже есть)

- Шов `Capability`/`CapabilityRegistry`/`ToolLoop` + порт `RepoIntrospector` +
  `SubprocessRepoIntrospector` (`asyncio.create_subprocess_exec`, без shell).
- Фикс-allowlist подкоманд: `_allow = {beadloom: {ctx,graph,why,search}, bd: {ready,show,list}}`;
  флаги режутся `_looks_like_flag`; для `bd list` сделан **фикс-allowlist arg-форм**
  `_BD_LIST_ARG_FORMS` (точные argv-кортежи) — тем же приёмом добавим git.
- `read_file` через `PrivacyGuard` (deny SOUL/`bob.db`/`.env`/`config`); BOB-034 открыл read-scope
  на `.claude/dev-docs` + `.claude/development/docs` (фича-доки). `architecture_context` = beadloom-граф.
- Связь чистая: каждый коммит — `[BOB-XXX] … (#PR)`; беад-ключ → `bd show` + фича-доки
  `.claude/development/docs/features/{KEY}/`.

## Решение (обзор)

Один read-only навык **`code_rationale`** («почему этот код такой») за существующим швом: по
пути/области/теме собирает **связку решений** из 4 уже-доступных источников и компактно её рендерит.
Оркестрация — в навыке (application); порт даёт сырые read-операции; git добавляется фикс-формами.

## Архитектура (DDD/Clean)

**Порт (`domain/ports.py`):**
- `RepoIntrospector.code_history(path: str) -> str` — git-история по пути (read-only). Реализация —
  через фикс-формы git (ниже). Остальное уже есть: `list_tasks` (=`bd show`), `read_file`,
  `architecture_context` (beadloom-граф).

**Инфраструктура (`subprocess_introspector.py`):**
- Добавить `"git"` в `_allow` с **фикс-allowlist invocation-форм** (как `_BD_LIST_ARG_FORMS`, БЕЗ
  произвольных флагов): `git log --oneline -- <path>` и `git log --grep=<BOB-key> --oneline`
  (опц. `git log --oneline -n <N> -- <path>`). `<path>` валидируется (внутри репо, не флаг);
  `<BOB-key>` валидируется по шаблону `BOB-\d+`/`bob-[a-z0-9.]+`. Таймаут + обрезка как у others.
- НЕ добавляем `git show`/`blame` в v1 (log достаточно; меньше поверхность; blame — опц. позже).

**Домен (`domain/introspection/...`, чистое):**
- Парсер `parse_bead_refs(git_log_text) -> list[str]` (вынуть `[BOB-XXX]` + `(#PR)` из строк) и
  `feature_doc_dir(bead_key) -> str` (ключ → `.claude/development/docs/features/{KEY}`). Чистые,
  тестируемые предикаты.

**Приложение (`application/capabilities/code_rationale.py`):**
- Фабрика `make_code_rationale_capability(introspector)` (образец — `inspect_architecture`/
  `recall_memory`), `permission="safe"`, вход — `query` (путь/область/тема). `execute`:
  1) `code_history(query)` → парс беад-ключей/PR;
  2) по ключам: `list_tasks(key)` (=`bd show`: описание+решения) + `read_file` фича-дока (PRD/RFC/
     PLAN, read-scope BOB-034);
  3) `architecture_context(query)` (beadloom-граф код↔доки);
  4) компактный рендер «почему» + честное **«история решения не зафиксирована»** при пустом (US-4).
  Дедуп/обрезка, чтобы не залить контекст.

**Композиция (`app.py`):** регистрация навыка в `_build_registry` при `introspection.enabled`;
`SubprocessRepoIntrospector` получает `git_bin` (дефолт `git`). НЕ добавлять в `goals.safe_capabilities`.

## 🔴 Приватность и безопасность (инвариант не ослаблен)

- git — только **фикс-формы read-log** (`create_subprocess_exec`, без shell, без произвольных
  флагов/путей-инъекций); нельзя `git show <secret>`/`git -C`/произвольное. `read_file` по-прежнему
  через `PrivacyGuard` (deny SOUL/`bob.db`/`.env`/`config`), читаются только фича-доки в read-scope.
- Источники рационала — git/беады/фича-доки/граф (всё не-секретное); личные данные не используются.
- Read-only; навык не в автономном safe-allowlist (диалоговый). Тесты на инвариант.

## Тестирование

- Домен-парсер (беад-ключи/PR из git-log, edge: несколько ключей, мусор, пусто); `feature_doc_dir`.
- Фикс-формы git: разрешены только log-формы; произвольный флаг/подкоманда (`show`,`push`,`-C`)
  отвергаются; путь-инъекция/`..` режутся.
- Навык (фейк-`RepoIntrospector`): связка код→беад→док→граф, компактный рендер, честное
  «не зафиксировано»; `permission="safe"`; приват-инвариант (не читает SOUL/db/.env/config);
  не в safe-allowlist; регрессии T3.A/tool-loop. Через `.venv/bin/pytest`, ≥80%.

## Риски и границы

- Только чтение, фикс-формы git — без записи/исполнения произвольного (T3.B — отдельно).
- Шумный/большой git-log → обрезка + лимит ключей; «не зафиксировано» вместо галлюцинации.
- Приват-инвариант — единственный острый риск, закрыт фикс-формами + `PrivacyGuard` + тестами.

## Альтернативы (отвергнуто)

- **Эмбеддинги/семантика всего кода** — тяжело, вне объёма; берём детерминированную связку git↔беад↔док.
- **Восстановление рационала из чат-логов** — личная память, приватность; отдельно/позже.
- **`git blame` в v1** — больше поверхность; `git log` по пути достаточно для «почему».

## Этапы (детализация — в PLAN)

1. **dev** — порт `code_history` + git фикс-формы в `SubprocessRepoIntrospector` + домен-парсер
   (`parse_bead_refs`/`feature_doc_dir`) + юнит-тесты.
2. **dev** — навык `code_rationale` (оркестрация связки) + регистрация в `app.py` + конфиг (`git_bin`).
3. **test** — US-1..5 + приват-инвариант + фикс-формы git + регрессии.
4. **review** — read-only/приват/git-формы/границы стадии/DDD; read-only.
5. **tech-writer** — `architecture.md` (рус): «архитектурный контекст», связка код↔решения. Gate.
