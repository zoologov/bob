<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE — BOB-112

> **Беада:** `bob-7fo` (P1, chore) · **Ветка:** `features/BOB-112`
> **Спека:** [BRIEF.md](BRIEF.md) · **Обновлено:** 2026-10-21

---

## Фокус

Гейты Боба снова проверяют то, что заявляют: релизный beadloom 9.0.0 в CI/VPS/локально,
красное на нетронутом графе разобрано по источникам, рукописная методология живёт в
проектном слое, config-check блокирующий.

## Дисциплина среза

Артефакты пишет только `uvx --from beadloom==9.0.0 beadloom …`. Editable из `~/beadloom` —
не для этого репозитория.

## Прогресс

- [x] `.1` инструмент и гейты — пин `beadloom==9.0.0` в CI/deploy (tree-sitter pin снят),
      `config-check` в блокирующем гейте (обходной шаг удалён), `install-hooks`,
      `setup-agentic-flow` (manifest, `explore.md`, guard-хук + PreToolUse в `settings.json`),
      `config-check --fix` двух auto-блоков, CLAUDE.md (aiogram; §6 закрытие BOB-108),
      ROADMAP (BOB-112 вписан — процессный гейт требовал).
      🔴 Попутно: `beadloom why` в 9.0.0 сменил разделитель дерева (`--[depends_on]--` вместо
      `----`) и добавил панель Impact Summary → `impact_digest` деградировал в де-фрейм; поймал
      тест на РЕАЛЬНОМ бинаре (§0.3 п.4). Починено TDD: 3 новых теста на фикстуре 9.0.0,
      саботаж регэкспа валит ровно их; mutation **59/59 убито**.
- [~] `.2` триаж lint/sync — 21 из 36 закрыты структурно (см. таблицу); 15 циклов → **BOB-113** (блокирует закрытие .2 и PR)
- [ ] `.3` рукописное → `.beadloom/flow/`, `--force`
- [ ] `.4` сайт
- [ ] `.5` review + гейты на финальном дереве

## Триаж lint 9.0.0 (заполняется в `.2`)

| Находка | Пар | Вердикт | Действие |
|---|---|---|---|
| `architecture-layers` layer:error | 20 | **структура графа**: вертикали — `part_of bob-domain` (tag `layer-domain`) → по 6.0.0 наследуют слой domain, хотя сами слоем не являются (так и написано в services.yml). Корень `bob` тоже слоевой (`layer-runtime`), поэтому просто снять тег с зонтика мало — цепочка дойдёт до корня | снять `layer-domain` с `bob-domain` и `layer-runtime` с `bob`; `kernel`/`runtime` держат свои теги сами; `app.py` → `# beadloom:feature=runtime` (замерено: рёбра переезжают на `runtime`). Вертикали — вне слоёв, как задумано в BOB-062.6a; их границы держат forbid_import-правила |
| `no-dependency-cycles` | 15 | **type-only**: 98 производных рёбер, 30 — только под `TYPE_CHECKING`; с ними одна SCC из 9 узлов, без них циклов **ноль**. В 9.0.0 у `forbid_cycles` нет `exempt`, резолвер type-only не отличает. Точный перебор: разомкнуть можно только убрав **16 из 20** type-only рёбер = **50 импорт-строк** (social-сущности 24, `handle_message` 12, чужие `ports` 8, events/self_improvement 6) | **Решение владельца: без полумер.** Контракты → `kernel`/`ports.py` — **BOB-113** (ветка от BOB-112, PR в неё). Никакого `warn`; BOB-112 ждёт BOB-113. ast-гард `test_no_runtime_import_cycles.py` остаётся вторым зубом |
| `coding-internals-no-usecases` live_stream.py:42 | 1 | **реальная** по букве правила, type-only по сути: адаптер берёт Protocol `StatusPanel` из usecases — порт лежит не в `ports.py` | перенести `StatusPanel`/`TypingKeepalive` Protocol в `coding/ports.py`, usecases ре-экспортирует |
| `sync-check` runtime ↔ wiring/* | 22 файла | 8.0.0: «untracked» = файлы узла БЕЗ `# beadloom:feature=` при том, что `tool_health.py` её несёт — частично аннотированный узел | все `wiring/*.py` + `app.py` получили `feature=runtime` / `layer=runtime` |

**Сделано в `.2` (кроме циклов):** слоевые ошибки 20 → **0** (`layer_population`: judged 17/99, skipped 82 — это вертикали, по замыслу), forbid_import 1 → **0** (`StatusPanel`/`TypingKeepalive` → `coding/ports.py`), runtime untracked → **0**. Попутно второй сдвиг формата 9.0.0: `beadloom diff` у изменённого узла перепечатывает старое+новое описание, добавленные узлы вылетали за кап `health_digest` — поймал живой тест на реальном бинаре после правки графа. Скелет diff + маркер «описание изменено (N строк скрыто)»; 5 новых тестов, саботаж валит ровно их. Новый гард `tests/test_no_runtime_import_cycles.py`: ast-обход, импорты под `TYPE_CHECKING` не считаются; на саботаже называет SCC из 10 узлов.

## Числа гейтов (релизный 9.0.0, чистый индекс)

| Момент | рёбер | lint errors | sync stale | config-check | exempt |
|---|---|---|---|---|---|
| до (2026-10-20) | 2255 | 925 строк / 36 находок | 1 | 2 drift + 8 unverified | 0 |
| после | | | | | |
