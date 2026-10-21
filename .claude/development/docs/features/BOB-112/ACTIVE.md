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
- [x] `.2` триаж lint/sync — 21 из 36 закрыты структурно (см. таблицу); 15 циклов → **BOB-113**
      (feature, PR #143 `features/BOB-113 → features/BOB-112`, смержен 8d1566e 2026-10-21):
      циклы 904 строк / 15 пар → **0/0** на `error` без `exempt`; depends_on 99 → 81; type-only
      рёбер 29 → 8 (все вниз по порядку вертикалей или в `kernel`); pytest 7986 → 8074.
- [x] `.3` рукописное → `.beadloom/flow/`, `--force` (2026-10-21).
      Факт: все 7 «hand-edited» файлов ролей/команд не менялись с BOB-001 — это снимок шаблонов
      beadloom того времени, правок Боба в них не было; `--force` принял композицию 9.0.0 без
      потерь (фронтматтер `name/tools/model` пяти ролей байт-в-байт тот же). Рукописное из
      `CLAUDE.md` (§0.1-факты, §0.2, §0.3, §3, §6, §7) — в `.beadloom/flow/claude/CLAUDE.md`
      как «Проектный слой Bob» (П.0.1 … П.7); построчная сверка: из 563 непустых строк старого
      файла отсутствуют 178 — старое ядро 2.1.0, заменённое ядром 9.0.0, английский §0.2
      (переведён) и хроника §6 (перенесена в П.6 целиком). Фрагменты ролей/команд —
      `roles/{dev,test,review,tech-writer}.md`, `commands/{coordinator,task-init,templates}.md`.
      `flow.yml`: `language: ru` (auto-блок `doc-language` → Russian, общие фрагменты ролей
      локализованы) + 2 объявленных `overlays.suppress` с `reason`/`until`: «Git — Trunk-based
      development» (403 на Free-плане) и «Template rules» (ядро `/task-init` печатает English,
      тег языка не читает → BDL-UX). `config-check` релизной сборкой: exit 0, **0 unverified,
      0 hand-edited**; кусачесть доказана саботажем (строка в `agents/dev.md` → exit 1
      «hand-edited», снята обратной правкой → exit 0).
      pytest на финальном дереве: 8074 passed, 16 skipped (живые смоуки), exit 0; `beadloom ci`
      на чистом индексе exit 0 — числа в таблице ниже.
- [x] `.4` сайт (2026-10-21). Портал 9.0.0 — новый скаффолд (своя тема 148 файлов, e2e-тесты,
      `site.generated.mjs` из блока `site:` в `.beadloom/config.yml`, оверлей `.beadloom/site/`
      копируется последним — та же философия, что проектный слой flow). Сделано по-9.0.0-ному,
      без переноса рукописной темы: `site:` (title Bob, description, base `/bob/`, repo_url),
      оверлей = наша домашняя (`index.md`, hero) + лендинг `public/bob-architecture.html` (версия
      с mermaid.js из `site/public`, не из `docs/`). Старый портал (79 файлов: рукописные
      `config.mjs`, тема, `package.json`, `sanitize-content.py`) снят целиком — 9.0.0 сам держит
      сырые `<` в доках (241 вхождение, сборка зелёная без санитайза). Замер до: прогон поверх
      копии старого портала — 9.0.0 «kept 5 files without beadloom:generated marker» и советует
      оверлей; прогон в чистую папку — 272 файла, VitePress build ✓. Итог: 273 файла (209
      скаффолд + контент + 2 из оверлея), `npm ci && npm run docs:build` локально ✓ — 56 html,
      base `/bob/`, home наша, лендинг на месте, ссылка на репозиторий в футере.
      Потеря, названная честно: ссылка «Схема архитектуры» в верхнем nav — `site:` не умеет
      свои пункты nav (есть только в hero/features домашней); оверлеить `config.mjs` ради неё —
      значит снова владеть файлом скаффолда → BDL-UX-предложение «site.nav extras».
      `deploy-site.yml` без изменений (коммитим контент, CI только `npm ci` + build на node 22).
- [ ] `.5` review + гейты на финальном дереве.
      🔴 Долг на `.5` (найден при пуше `.3`): pre-push хук 9.0.0 вызывает `beadloom` с PATH, а это
      **editable-сборка** (`uv tool list`: beadloom v7.0.0 из `~/beadloom`, ветка BDL-083), чья
      `config-check` считает 8 композированных файлов «stale vs CORE» — шаблоны другой версии.
      Хук per-clone и без пина → его вердикт не про CI (П.0.1). Решение владельца: `uv tool
      install beadloom==9.0.0 --force` (dev beadloom — через `uv run` в `~/beadloom`) или иной
      способ пина; до него пуши ветки идут `--no-verify` с записанной причиной, а гейт релизной
      сборкой гоняется координатором руками (как и сделано для `.3`/`.4`).
      🔴 Долг на `.5`, замечен в `.3` и был в том же составе уже в первом замере 9.0.0: lint
      печатает **36 `rule_liveness: warn`** — правила, которые не могут сработать: 24 про
      `bob/identity/usecases*` и `bob/presence/usecases*` (таких пакетов нет), 10 про glob
      `bob/app` (не матчит ни один из 419 import-путей — composition-root-правила проверяют
      ничего), 2 про `src/bob/coding/untrusted_repo.py` (файла нет). Это не «сдвиг вердикта»,
      а мёртвые правила = отключённая проверка без срока; чинить структурно (glob или снятие
      правила с записью), не гасить.

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
| после `.3` (2026-10-21, `beadloom ci` exit 0) | 121 (узлов 23, derived) | **0** (warn 37: 36 `rule_liveness` + 1 `architecture-layers` reach 15/81) | **0** | **0** (1 info-warn «project layer in effect», 2 declared suppressions) | 0 |
