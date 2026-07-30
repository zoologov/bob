> **Status:** Approved
> **Type:** feature
> **Created:** 2026-07-30
> **Issue:** BOB-067

# CONTEXT — BOB-067 Repo-navigation

## Состояние

- **Фаза:** реализация (dev → test → review → tech-writer).
- **Ветка:** `features/BOB-067` (от `main` b1b08d8).
- **Домен:** `bob.capabilities` (порт + usecase + адаптер), wiring в `bob.runtime`. Шаблон — BOB-017.

## Ключевые решения

1. **Полный доступ ко всему репо** — осознанный выбор владельца (Боб = равный, работает со всем
   репо как инженер). `PrivacyGuard.allows_path` → allow любого пути под корнем репо.
2. **Граница = поддерево репо, не вся ФС.** Escape за корень (`..`/абсолют вне репо) — deny (INV-N3).
3. **`sanitize()` сохранён** — секрет-значения (`sk-`, `KEY=value`, api-key) → `[REDACTED]` на выходе,
   чтобы литеральные токены не утекали во внешний Qwen (INV-N4). Полный доступ ≠ утечка секрет-строк.
4. **Два новых инструмента:** `list_dir` (перечень записей директории) + `find_file` (поиск по
   имени/паттерну в дереве). Read-only, за `introspection.enabled` (default on) — живые сразу.
5. **`.git/` пропускается** в `find_file` — практичность (бинарь/раздувание), не безопасность.
6. **read-only** — никаких мутаций (запись — через `coder`/`/code`).

## Стандарты кода (из CLAUDE.md §0.1)

- Python 3.12+, asyncio; DDD + Clean Architecture (домен чист от I/O; адаптер шеллит/ходит на диск).
- TDD (test-first) · BDD `.feature` (behavior-bearing) · Mutation ≥85% на чистых ядрах.
- ruff (lint+format) · mypy --strict (src+tests) · без `Any`/`type: ignore` без причины.
- beadloom: reindex --full + sync-check + lint --strict + ci перед PR.

## Опорные файлы

- `src/bob/capabilities/introspection/privacy_guard.py` — ЧИСТОЕ ядро (менять allows_path, беречь sanitize).
- `src/bob/capabilities/ports.py` (~:265 RepoIntrospector) — +2 метода порта.
- `src/bob/capabilities/adapters/introspection/subprocess_introspector.py` — реализация list_dir/find_file.
- `src/bob/capabilities/usecases/read_code.py` — ОБРАЗЕЦ capability.
- `src/bob/capabilities/usecases/{list_dir,find_file}.py` — НОВЫЕ фабрики.
- `src/bob/runtime/wiring/capabilities.py` — регистрация.
- `src/bob/personality/usecases/voice_composer.py:97` `_CAPABILITY_PREFACE` — опц. анти-нарратив nudge.

## DoD

pytest (весь) · mypy --strict (src+tests) · ruff · beadloom reindex --full && lint --strict &&
ci GREEN · mutation ≥85% на PrivacyGuard · BDD-сценарии зелёные · живой прогон (Боб реально листит/ищет).
