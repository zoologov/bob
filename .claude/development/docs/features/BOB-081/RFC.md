> **Status:** Approved
> **Type:** feature
> **Created:** 2026-08-01
> **Issue:** BOB-081

# RFC — Dev-интроспекция: git-история + трекер (read-only)

## Резюме решения

Каркас есть (BOB-067): реестр capability, tool-loop, возврат результата модели, **санитайз секретов на
всём выводе `_run`** (INV-3 бесплатно), гейт `is_guest` (авторизованный ход → инструменты, гость → нет —
**INV-4 бесплатно**). `bd list/show` и `git log` (по bead-key/пути) уже в интроспекторе. Доделываем
**узко**: (1) repo-wide форму `git log --oneline -n N`, (2) read-подкоманду `bd comments`, (3) тонкие
разговорные обёртки + чистое ядро валидации, всё за под-флагом `introspection.dev_tools` (default OFF).

## Разведанные seam-точки (авторитетно)

- Реестр: `capabilities/usecases/registry.py:45` (register/manifest/dispatch/describe); tool-spec
  `registry.py:112`; контракт `capabilities/ports.py:168` `Capability` (name/description/input_schema/
  permission/execute). Пример для зеркала — `capabilities/usecases/list_dir.py:35-86`.
- Интроспектор: порт `capabilities/ports.py:266` `RepoIntrospector` (`code_history(path):337`,
  `list_tasks(query):328`); адаптер `capabilities/adapters/introspection/subprocess_introspector.py`.
  - git = ТОЛЬКО `log` (`_GIT_SUBCOMMANDS:65`); формы требуют `--grep=<key>` или `-- <path>`
    (`_validate_git_args:558`); **repo-wide `git log -n N` НЕ выразим** — добавить форму.
  - bd = `ready/show/list [--status enum]` (`_BD_SUBCOMMANDS:62`, статусы `open/in_progress/blocked/
    deferred/closed :71`); **`bd comments` НЕТ** — добавить подкоманду.
  - Безопасный запуск: `_run:511` → `create_subprocess_exec` (не shell) + `wait_for(timeout=30s)` +
    kill/drain; allowlist бинарь+подкоманда+форма; **санитайз `self._guard.sanitize(...)` на выводе :529**.
- Санитайз: `capabilities/introspection/privacy_guard.py:148 _sanitize` (токены/ключи/env/telegram/sk-);
  применяется генерично в `_run`.
- Флаг-мастер: `wiring/parameters.py:458 _build_introspection_enabled` (`introspection.enabled`);
  регистрация — `wiring/capabilities.py:93-105`; бинарники `bd_bin`/`git_bin` — `loader.py:309` +
  `wiring/capabilities.py:145`.
- Гейт: `personality/usecases/voice_composer.py:357` (`is_guest` → all-or-nothing tool-loop). Отдельный
  privileged-путь `application/usecases/privileged_fulfiller.py:107` строит ToolLoop над тем же реестром.
- Результат → модель: `tool_loop.py:127/199/276` (`_render_result`; dict → json.dumps; фидбек в диалог).

## Чистое ядро (валидация форм — mutation-цель)

**`capabilities/introspection/dev_query.py`** (layer=domain, I/O-free):
```python
_BEAD_ID_RE = re.compile(r"^(?:BOB-\d+|bob-[a-z0-9]+)(?:\.\d+)?$", re.IGNORECASE)
_TRACKER_STATUSES = frozenset({"open","in_progress","blocked","deferred","closed"})
_MAX_COMMITS = 50

def clamp_commit_count(n: int | None) -> int: ...        # None→дефолт(10); в [1, _MAX_COMMITS]
def validate_bead_id(raw: str) -> str: ...               # только форма bead-key, иначе ValueError (для show/comments)
def normalize_status(raw: str | None) -> str | None: ... # в allowlist или None; синонимы «в работе»→in_progress, «закрытые»→closed
```
Детерминированно, без БД/subprocess → TDD + mutation ≥85%. Инвариант: id/status/count пропускаются в
subprocess ТОЛЬКО пройдя эти предикаты (защита формы, часть INV-1).

## DATA — расширить интроспектор (read-only формы)

`subprocess_introspector.py` + порт `capabilities/ports.py`:
- **git repo-wide:** новая allowlist-форма `git log --oneline -n <N>` (без path/grep) в `_validate_git_args`;
  порт-метод `recent_commits(count: int) -> str` (через `clamp_commit_count`). Остальные git-подкоманды
  (`show`/`diff`/`blame`) остаются запрещены.
- **bd comments:** добавить `comments` в `_BD_SUBCOMMANDS` + форму `bd comments <id>`; порт-метод
  `task_comments(bead_id: str) -> str` (через `validate_bead_id`). `bd create/update/close` — не в
  allowlist (жёсткий INV-1).
- **bd show/list:** порт-методы `show_task(bead_id)` (`bd show <id>`, `validate_bead_id`) и
  `list_tasks(status)` (`bd list [--status <enum>]`, `normalize_status`). Переиспользовать существующую
  `list_tasks`-инфру; расширить статусом, если текущая форма его не принимает.
- Санитайз/таймаут/allowlist наследуются `_run` — не дублируем.

## TOOLS — разговорные обёртки (зеркало list_dir.py)

Новые capability-usecases в `capabilities/usecases/` (permission `"safe"`), каждый над `RepoIntrospector`:
- `recent_commits` — вход `{"count": {"type":"integer"}}` (опц.). Описание: «Верни РЕАЛЬНЫЕ последние N
  коммитов из git — не выдумывай».
- `list_tasks` — вход `{"status": {"type":"string","enum":[...]}}` (опц.). (Если существующий `list_work`
  уже покрывает листинг — расширить его статусом, не плодить дубль; решает dev по факту кода.)
- `show_task` — вход `{"id": {"type":"string"}}`. Детали задачи.
- `task_comments` — вход `{"id": {"type":"string"}}`. Комментарии/чекпоинты задачи.
Описания инструментов подчёркивают: РЕАЛЬНЫЕ данные, пусто→честно «не нашёл» (INV-5), только чтение.

## Флаг и регистрация

Под-флаг **`introspection.dev_tools`** (bool, default OFF; читать как `_build_introspection_enabled`,
helper в `wiring/parameters.py`). Регистрировать новые инструменты в `wiring/capabilities.py:93-105`
внутри introspection-блока, но за под-флагом: OFF → инструменты не регистрируются (Боб их не видит,
ноль изменений). Активируем `introspection.dev_tools: true` в running-config после ревью (образец
активации [[bob-072-stream-read]]). Мастер `introspection.enabled` уже ON (навигация BOB-067 работает).

## Границы (как в PRD)

Никакой записи (git commit/push, `bd create/update/close`) — не в allowlist. Coder не трогаем. Без
дашбордов. Без проактивного фонового лазанья (инструменты — по ходу диалога).

## Инварианты → реализация

- INV-1 read-only → allowlist только read-подкоманд/форм; write-подкоманды не добавляются; validate-предикаты.
- INV-2 заземление → результат dict/str возвращается модели (`tool_loop`), Боб пересказывает.
- INV-3 без секретов → `_run` санитайз (наследуется).
- INV-4 authz → существующий `is_guest`-гейт (гость без инструментов).
- INV-5 честность → описания инструментов + пустой вывод как есть; модель не фабрикует.
- INV-6 bd read-only → `bd list/show/comments` в allowlist, subprocess-exec без shell, таймаут.

## Риски и меры

- **Утечка секретов из git/bd вывода** → генеричный санитайз в `_run` + живой негативный смоук на РЕАЛЬНОМ
  выводе (урок BOB-067: расширение доступа обнажает бэкстоп — смоук обязателен).
- **Прорыв к write-подкоманде** → allowlist подкоманд + форм; ревью-беад отдельно проверяет, что ни одна
  мутирующая форма не выразима; unit на отказ `bd close`/`git commit`/инъекции аргументов.
- **Инъекция аргументов** (id с флагами/`;`) → `validate_bead_id`/`_looks_like_flag`; exec без shell.
- **Флуд/таймаут** → count кап (≤50) + существующий 30s timeout + truncate.
- **Гость получил доступ** → тест: guest-ход не получает инструменты (гейт `is_guest`).

## Тест-стратегия

- **Unit/TDD:** `dev_query` (clamp_commit_count границы; validate_bead_id принимает bead-key/отвергает
  флаги-инъекции; normalize_status синонимы/allowlist/None) — **mutation ≥85%**. Интроспектор с fake-runner:
  recent_commits форма, task_comments/show_task/list_tasks формы; 🔴 **отказ** write-подкоманд
  (`bd close`, `git commit`, `git show`) и argument-инъекций; санитайз применён к выводу.
- **BDD `.feature`** (`tests/acceptance/`, через границу capability/tool-loop с fake introspector): S1
  recent_commits, S2 list по статусу, S3 show + comments, S5 пусто→честно + guest→без инструментов.
- **Живой смоук (после активации флага):** owner: «глянь последние 10 коммитов» → реальные [BOB-08x];
  «покажи закрытые задачи» → реальные беады; «комментарии к BOB-076» → чекпоинты. 🔴 Негативный: убедиться,
  что вывод git/bd на реальном репо НЕ содержит секретов; что `bd close`-подобные формы недоступны.
