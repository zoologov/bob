<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PRD: BOB-062 — «Domain-first реорганизация + доки» (эпик, Фаза 3)

> **Status:** Approved
> **Created:** 2026-07-02
> **Type:** epic · Фаза 3 аудита · BOB-Issues #1–6, #9–18, #30
> **Owner:** Владимир · **Автор:** Bob (Claude Code)
> **Предшественники:** Фаза 1 (BOB-063/064 ✅) · Фаза 2 (BOB-065 ✅ — split ports, граф 28 узлов, 11 AaC-правил)

---

## Проблема

Код Боба сейчас **слоисто-первый** (`domain/` · `application/` · `infrastructure/`): одна бизнес-
способность (напр. «личность» или «память») размазана по 2–3 верхним каталогам. Смотря на дерево,
НЕ видно «что есть что» — не screaming architecture. Плюс два God-файла (`handle_message.py` 3523,
`app.py` 2815) и монолит доков (`architecture.md` ~4100 строк, per-feature SPEC/DOC отсутствуют).

Фаза 2 поставила **рельсы** (детальный граф + AaC-правила + гранулярные аннотации), но код физически
не двигался. Фаза 3 — собственно переезд в domain-first, наполнение доков и растворение монстров,
**внутри** этих рельс (правила ловят ошибки переезда в CI в реальном времени).

## Цели

- **Screaming architecture.** Бизнес-модули — верхнего уровня; смотря на дерево, сразу понятно, что
  делает система. Технические модули (`application`/`infrastructure`/`runtime`) — на своих местах.
- **Когезия вместо слоёв.** Каждый бизнес-модуль — вертикальный срез (свои domain-типы, порты,
  use-cases рядом); Clean-Architecture-границы внутри энфорсятся правилами (Фаза 2), НЕ каталогами.
- **Монстры растворены.** `handle_message.py` → тонкий оркестратор + ~14 когезивных коллабораторов
  по целевым модулям (#9); `app.py` → `runtime/` (composition root) + инфра-адаптеры (#10).
- **Доки как у beadloom.** Per-node SPEC/DOC генерятся и наполняются; `architecture.md` ужат до
  навигационного обзора (таблица + Mermaid + ссылки); getting-started + гайды (#3–#5).
- **Каркас с зубами закрыт.** После переезда — правило слоёв уже `error` (Ф2); удалить ports-шим (#18).

## Не-цели

- НЕ менять поведение Боба (весь эпик — behavior-preserving; рантайм-инварианты сохраняются).
- НЕ добавлять фичи продукта (это отдельные роадмап-эпики: web_research, T3-кодер и т.д.).
- НЕ переписывать тесты по существу (адаптировать импорты/пути — да; менять смысл — нет).

## Целевая структура (утв. в Фазе 2)

**Бизнес-модули (верхний уровень):** `personality`(+voice) · `conversation`(floor/адресность/brevity/
судьи/анти-тик) · `memory` · `capabilities`(шов+навыки: web/diagrams/introspection) · `social`
(identity/first-impression/relationships/authz/permission) · `proactivity`(drive/goals/self-improvement)
· `coding`.
**Технические модули:** `application`(кросс-доменная оркестрация) · `infrastructure`(llm/web/telegram/
persistence/config) · `runtime`(composition root ex-`app.py` + AgentRuntime/heartbeat/event-bus).
`docs/domains/<module>/` зеркалит структуру 1:1.

## Подход: вертикальные срезы, PR за PR

Эпик режется на **вертикальные срезы по модулям**, порядок от самого когезивного/безопасного к
сложному: **coding → memory → proactivity → social → conversation → personality/capabilities →
runtime/application**. Каждый срез — отдельная фича/PR, несёт: переезд кода + `# beadloom:feature/
component` аннотации + перецеливание граф-узлов + свои SPEC/DOC (наполненные) — **вместе**. Монстры
растворяются внутри соответствующих срезов (`handle_message` кусками; `app.py` в срезе `runtime`).

## Пользовательская ценность

Сопровождающий (Владимир) и Боб-кодер: дерево читается с первого взгляда; изменение способности
локально в одном модуле; доки актуальны и гранулярны; CI ловит нарушение границ до мержа.

## Критерии успеха (эпик)

- Дерево `src/bob/` — domain-first; каждый бизнес-модуль когезивен; `beadloom lint --strict` зелёный
  с правилом слоёв в `error`.
- `handle_message.py` и `app.py` растворены (нет God-файлов > порога `no-monster-modules`; флип в `error`).
- `architecture.md` — навигационный обзор; per-module SPEC/DOC наполнены; `beadloom ci` зелёный.
- Поведение идентично (pytest зелёный на каждом срезе; рантайм-инварианты целы); ports-шим удалён (#18).
- BOB-Issues #1–6, #9–18 закрыты.

## Риски

- **Большой blast radius** переезда (импорты 141-файл-масштаба) → строго behavior-preserving, срез за
  срезом, транзитные re-export-шимы на границах, тесты как страховка на каждом шаге.
- **Рантайм-инварианты** (verify-once-per-turn, анти-повтор, floor-advance, essential-vs-decorative,
  feature-flag off→None→inert, boot-order, shared-instance) — не сломать при перемещении (детализируем
  в RFC/CONTEXT как чек-лист среза).
- **Объём** → эпик умышленно инкрементальный: каждый срез самостоятельно ценен и мержится отдельно;
  не ломаем trunk (main всегда зелёный).

## Открытые вопросы (к RFC)

- Гранулярность среза: один модуль = один PR, или крупные модули (personality/conversation) бить
  дальше? 
- Стратегия переезда: `git mv` + re-export shim на старом пути (для плавности импортов) vs атомарный
  переезд с обновлением всех импортёров в одном PR?
- Порядок растворения `handle_message` относительно срезов conversation/personality (он их пересекает).
- Куда именно уезжает `runtime/` и как обойтись без даунтайма composition-root при переносе `app.py`.
