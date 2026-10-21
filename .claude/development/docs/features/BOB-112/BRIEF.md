<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF — BOB-112: beadloom 2.1.0 → 9.0.0

> **Тип:** chore · **Приоритет:** P1 · **Беада:** `bob-7fo` (срезы `.1`–`.5`) · **Issues:** закрывает условие окончания BOB-108
> **Ветка:** `features/BOB-112` · **Заведено:** 2026-10-21 · **Status:** Approved

---

## Проблема

Боб настроен под beadloom **2.1.0** (июнь 2026). Актуальный релиз — **9.0.0** (2026-10-10), между
ними семь мажоров. Последний CI на `main` был 19 августа и ставил 2.1.0; с тех пор ни один гейт
не видел, что делает с проектом свежая установка — а именно её поставят `ci.yml` и
`deploy-bob.yml` при следующем прогоне (`uv tool install beadloom` без пина).

Замерено 2026-10-20 на нетронутом графе и чистом индексе (`rm beadloom.db && reindex`):

| | 2.1.0 | релизный 9.0.0 |
|---|---|---|
| `reindex` | 1487 импорт-рёбер | **2255** — видит импорты внутри `if TYPE_CHECKING:` и функций (2.2.0) |
| `lint --strict` | 0 нарушений, exit 0 | **exit 1**: 20 `layer:error`, 15 пар циклов (904 строки), 1 `forbid_import` |
| `sync-check` | exit 0 | **exit 2**: `services/runtime.md` ↔ 22 файла `runtime/wiring/` (8.0.0 — пара на каждый файл) |
| `config-check` | — | 2 auto-блока дрейфнули; 8 рукописных файлов ролей/команд `unverified`; нет `flow-manifest.json` → вердикт ослаблен до warn |
| `doctor` | — | 22 файла runtime вне графа; `getting-started.md` без ref_id; «version 2.1.0 vs 1.0.0» |

Это сдвиг вердиктов beadloom, а не регрессия кода Боба. Но «красное от инструмента» и
«красное от нас» в гейте неразличимы, и пока это не разобрано, гейт нельзя ни включить
(всё красное), ни оставить как есть (CI на 2.1.0 — витрина, не проверка).

**Источники красного (по changelog beadloom):**
- **6.0.0** — `architecture-layers` наследует слой через `part_of` и судит соседей одного слоя.
  Module-verticals (`capabilities`, `coding`, `conversation`, …) — `part_of` зонтика `domain`
  с тегом `layer-domain`, и их зависимости на `router`/`runtime-app`/`persistence`/`telegram`
  теперь читаются как «domain → выше». 20 пар.
- **2.2.0** — новые рёбра из `TYPE_CHECKING`/функций: 15 пар циклов между вертикалями
  (`capabilities↔personality` 149, `capabilities↔usecases` 141, `social↔runtime-app` 126, …)
  и `coding/adapters/live_stream.py:42` (type-only импорт `usecases` под `TYPE_CHECKING`).
- **8.0.0** — `sync-check` держит пару на каждый файл узла с частично аннотированными
  исходниками: `runtime.md` не называет `wiring/*`.
- **3.0.0 / 9.0.0** — `config-check` сравнивает с композицией, нужен `flow-manifest.json`;
  появился **проектный слой** `.beadloom/flow/{roles,commands,claude}/` — тот самый оверлей,
  отсутствие которого (BDL-UX #152) заставило нести методологию в сам beadloom (BDL-059).

**Условие окончания BOB-108 наступило:** PyPI 9.0.0 содержит шаблоны BDL-059 — три файла ролей
из списка дрейфа ушли. `config-check` возвращается в блокирующий гейт — после починки.

## Решение

Один PR, пять срезов. Единая дисциплина: **все артефакты пишутся релизным `beadloom==9.0.0`**
(`uvx --from beadloom==9.0.0 beadloom …`), той же сборкой, что ставит CI и VPS. Локальный
editable из `~/beadloom` (ветка `features/BDL-083`) остаётся для разработки beadloom, но не
для артефактов Боба — иначе «у меня зелено» снова ничего не доказывает про CI (урок BOB-108).

**`.1` Инструмент и гейты.**
- Пин `beadloom==9.0.0` в `ci.yml` и `deploy-bob.yml`; бамп — осознанным коммитом. Пин
  `tree-sitter<0.26` снять: 9.0.0 пинит сам (`tree-sitter>=0.25,<0.26`), комментарии обновить.
- `config-check` — обратно в блокирующий Beadloom Gate; обходной шаг и его аннотации удалить.
- `install-hooks` заново (pre-commit теперь `sync-check --staged`).
- `setup-agentic-flow` (без `--force`) → `flow-manifest.json`, `agents/explore.md`,
  `hooks/beadloom-guard.sh`, PreToolUse-хуки в `settings.json`, блок в `.gitignore`.
- `config-check --fix` для двух auto-блоков (AGENTS.md, CLAUDE.md project-info).
- CLAUDE.md §0.1: рукой написано «`python-telegram-bot`», код на **aiogram** — поправить.

**`.2` Триаж lint/sync.** По каждой из 36 находок — вердикт с доказательством:
- реальная зависимость → либо правка кода, либо `exempt` с `reason` и `until`;
- type-only (`TYPE_CHECKING`) → вынести типы в `ports.py`/kernel или `exempt` с reason
  «type-only, 2.2.0 extraction»;
- структура графа (6.0.0: вертикаль ≠ слой domain) → теги/`part_of` в `services.yml`.
  🔴 Не «35 exempt оптом»: каждый с причиной, иначе гейт снова показывает зелёное, не проверив.
- `services/runtime.md` называет `wiring/*`; `getting-started.md` получает ref_id или
  объявляется вне графа. _Решение (.8, 2026-10-21, по Minor-2 ревью): `getting-started.md` —
  руководство по развёртыванию, не документ узла; ref_id ему не присваивается (пара с кодом
  корня `bob` была бы ложной и вечно stale). У `doctor` 9.0.0 нет способа объявить документ вне
  графа (в конфиге нет ключа, проверено по `application/doctor.py`), поэтому 1 `[warn]` остаётся
  и записан в BDL-UX-draft (запись про популяцию «документы вне графа»); это не графовый warn._

**`.3` Рукописное — в проектный слой.** Содержимое `agents/{dev,test,review,tech-writer}.md`,
`commands/{coordinator,task-init,checkpoint,templates}.md`, `CLAUDE.md` сверяется с композицией
9.0.0; всё проектное (§0.2 парадигмы, §0.3 верификация, Cohesion, автономия координатора,
русский язык документов) переезжает в `.beadloom/flow/{roles,commands,claude}/`; затем
`setup-agentic-flow --force` принимает композированные ядра. Критерий: `config-check` exit 0
**без** `unverified`/`hand-edited`. Правило «документы на русском» (§3) перестаёт быть
исключением из vendored-файлов — оно живёт в слое.

**`.4` Сайт.** `docs site` релизным 9.0.0 поверх закоммиченного портала (переименование
`entities/graph-edge→graph-edges` и т.д., снятие 42 файлов темы, футер). Коммит контента, как
и прежде (память: контент коммитится, CI только собирает VitePress).

**`.5` Review.** Роль `review` по всему PR + перепроверка гейтов координатором на финальном
дереве: `rm -f .beadloom/beadloom.db && uvx --from beadloom==9.0.0 beadloom ci` — exit 0, и
отдельно `lint --strict` / `sync-check` / `config-check` / `doctor` с **числами** (сколько
рёбер, сколько exempt, сколько pairs), не только цветом (§0.3 п.1, п.6, п.8).

## 🔴 Циклы: решение владельца 2026-10-21 — без полумер

Триаж `.2` показал: из 98 производных рёбер 30 — только под `TYPE_CHECKING`; с ними одна
компонента из 9 узлов, без них циклов нет. У `forbid_cycles` в 9.0.0 нет `exempt`, резолвер
type-only не отличает. Предложенная временная мера (`warn` + собственный ast-гард + `until`)
**отвергнута владельцем**: связь по контракту — всё равно связь, контракты сцепленных
контекстов переезжают в `kernel`/`ports.py`. Это **BOB-113** (feature, своя спека; ветка от
`features/BOB-112`, PR в неё). BOB-112 **не уходит в `main`, пока BOB-113 не вернул
`lint --strict` в 0 на `error`** — никакого `warn` в `rules.yml`. Собственный гард
`tests/test_no_runtime_import_cycles.py` остаётся как второй, независимый от beadloom зуб
на runtime-циклы (он не полумера: он дополняет правило, а не подменяет его).

## Что НЕ входит

- Обновление зависимостей Боба (`uv lock --upgrade`) — отдельный chore следом.
- Сам перенос контрактов — BOB-113 (см. выше); BOB-112 ждёт его, а не обходит.
- Выкатка на VPS (деплой по тегу; beadloom там обновится следующим релизом Боба).

## Acceptance

- [x] `ci.yml` и `deploy-bob.yml` пинят `beadloom==9.0.0`; `config-check` в блокирующем гейте (.1; ревью .5 подтвердило)
- [x] На чистом индексе релизным 9.0.0: `lint --strict` 0, `sync-check` 0, `config-check` 0
      без `unverified`, `docs audit` 0, `doctor` без `[warn]` по графу
- [x] Каждый `exempt` несёт `reason` + `until`; их число и список — в ACTIVE.md (exempt: 0; declared suppress: 2, беады bob-933/bob-yjv)
- [x] `flow-manifest.json` в git; рукописное — в `.beadloom/flow/`; `explore.md` и guard-хук на месте (.3)
- [x] Сайт перегенерирован 9.0.0, закоммичен (.4; перегенерация на запушенном HEAD перед PR — Minor-1 ревью)
- [ ] CI по PR зелёный **с** блокирующим config-check; аннотация-обход BOB-108 удалена
- [ ] BDL-UX: заведён баг на обрезанную строку `Stack: … aiogram, s` в auto-блоке — **не выполнено**: 12 записей подготовлены в `BDL-UX-draft.md`, в лог beadloom переносятся после BDL-083 S4 (решение владельца 2026-10-21, беада `bob-v25`); до переноса пункт открыт
