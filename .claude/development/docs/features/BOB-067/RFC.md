> **Status:** Approved
> **Type:** feature
> **Created:** 2026-07-30
> **Issue:** BOB-067

# RFC — Repo-navigation capabilities + полный доступ к репо

## Обзор решения

Фикс = **один логический юнит** в домене `bob.capabilities` по существующему шаблону
(BOB-017 self-introspection). Ни `conversation`, ни бот-роутинг не трогаем. Три части:

1. **`PrivacyGuard` → полный репо** (чистый домен). `allows_path` возвращает True для любого
   пути, резолвящегося ПОД корнем репо; сохраняет отказ на выход за корень (`..`/абсолют вне репо)
   и **сохраняет** `sanitize()` (секрет-backstop). Это осознанный выбор владельца (INV-N2/N3/N4).
2. **Два новых read-only capability:** `list_dir` + `find_file` (порт + адаптер + фабрики + wiring).
3. **`read_code`** автоматически расширяется (тот же `allows_path`) — читает любой файл репо,
   секрет-значения `[REDACTED]`.

## Компоненты и seam-точки

### 1. PrivacyGuard (`src/bob/capabilities/introspection/privacy_guard.py`)

- `allows_path(path)`: сейчас — segment-prefix по `_ALLOWED_ROOT_SEGMENTS`. Меняем на: путь
  резолвится (`_resolve`, `..` collapsed) относительно `repo_root`; `target.relative_to(root)`
  успешен ⇒ **allow** (полный репо); `ValueError` (вышел за репо) ⇒ **deny**. `_resolve` +
  repo-escape логика сохраняются как есть (INV-N3).
- `sanitize(text)` — **без изменений** (INV-N4): `sk-`-токены, `KEY=value`, api-key паттерны → `[REDACTED]`.
- `ALLOWED_ROOTS` — константа используется адаптером (`subprocess_introspector.py:394 for root in
  ALLOWED_ROOTS` — «якорные» директории для чего-либо). Обновить/оставить совместимо: если это
  «корни для перечисления», заменить на repo-root (`(".",)` / прямой repo_root). dev сверяет
  использование и не ломает адаптер. Docstring/комментарии домена обновить под полный-репо.

### 2. Порт RepoIntrospector (`src/bob/capabilities/ports.py`, ~:265)

Добавить два метода (read-only), рядом с `read_file`/`search_code`:
- `list_dir(path: str) -> ...` — записи директории: имя, тип (file/dir), размер; НЕ рекурсивно.
- `find_file(pattern: str) -> ...` — glob/имя по дереву репо; список repo-relative путей.

### 3. Адаптер (`.../adapters/introspection/subprocess_introspector.py`)

Реализовать оба через `pathlib`/`os.scandir` (read-only, subprocess не нужен):
- guard: каждый путь через `self._guard.allows_path` (полный репо, отказ на escape);
- `list_dir`: `os.scandir` целевой директории; сортированный вывод имя+тип+размер; несуществующая/
  не-директория → честный пустой/ошибочный результат (INV-N5); вывод через `sanitize`.
- `find_file`: обход дерева репо с `Path.rglob`/ручной walk; **пропускать `.git/`** (практичность:
  бинарь, раздувает — НЕ вопрос безопасности) и симлинки-наружу; кап на кол-во совпадений (напр. 200)
  с честной пометкой «усечено»; вывод через `sanitize`.

### 4. Фабрики capability (`src/bob/capabilities/usecases/`)

Новые `list_dir.py` + `find_file.py` по образцу `read_code.py`: класс с `name`,
`_DESCRIPTION` (чёткое, чтобы LLM ВЫЗЫВАЛ инструмент, а не нарративил), `input_schema`,
`execute()` (диспетч в порт, оборачивает ошибки в строку-результат), + `make_*_capability(...)`.

### 5. Wiring (`src/bob/runtime/wiring/capabilities.py`)

За тем же `introspection.enabled` (default on): импорт + `registry.register(make_list_dir_capability(introspector))`
и `make_find_file_capability(introspector)` рядом с `read_code`. Никаких новых флагов.

## Опция (вторично, по решению review): анти-нарратив nudge

`_CAPABILITY_PREFACE` (`voice_composer.py:97`, «Эти возможности GUPPI исполняет для тебя»)
провоцирует ролеплей «GUPPI пошёл». Лёгкая правка формулировки — «докладывай РЕЗУЛЬТАТ вызова
инструмента, а не намерение» — может усилить INV-N1. Не блокирует фичу (главное — реальные tools);
review решает, включать ли в scope.

## Тестирование (пирамида §0.2)

- **Unit/TDD (чистое ядро):** `PrivacyGuard.allows_path` — полный репо allow (`.beadloom`, `config`,
  корень) + escape deny (`../../etc/passwd`, абсолют вне репо) + `sanitize` по-прежнему редактит.
- **Unit адаптер:** `list_dir`/`find_file` над временным деревом (реальные записи, `.git`-skip,
  пустая директория, несуществующий путь, кап).
- **BDD `.feature`** (behavior-bearing): «Боб листит директорию», «Боб находит файл», «Боб честно
  говорит „не найдено"», «выход за репо отклонён» — через границу (fake gateway / tool-loop),
  наблюдаем реальный результат, не приватное состояние.
- **Mutation (≥85%)** на чистом `PrivacyGuard` (домен-ядро) + любых чистых политиках find/list.

## Forward-compat

Инструменты участник-агностичны (owner-only tool-loop как сейчас). Для BobNet/реплик
[[bob-replicas-as-bobiverse]] тот же порт переиспользуется. Изменение guard'а — расширение
инварианта, не слом: старые разрешённые пути остаются разрешены.
