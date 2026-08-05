# ACTIVE: BOB-091 — Боб владеет read-only beadloom

> **Last updated:** 2026-08-05

---

## Сейчас в работе

| Беада | Статус | Что |
|---|---|---|
| `bob-cjz.1` | ✅ код готов (ждёт верификации координатора) | Срез 1: схема (`graph` обзорная + подробная C4) + влияние (`why`, сжато) |
| `bob-cjz.2` | ○ ждёт .1 | Срез 2: остальной read-only (`status` `prime` `diff` `doctor` `sync-check` `lint`) |
| `bob-cjz.3` | ○ ждёт .2 | Ревью: безопасность argv-шва |

Ветка `features/BOB-091`, коммит на волну, один PR в main.

## Прогресс

- 2026-08-05 — беады заведены (`bob-cjz` + 3 среза), BRIEF утверждён, срез 1 запущен.
- 2026-08-05 — **срез 1 реализован** (не закоммичен, беада не закрыта — верифицирует
  координатор). Чистые ядра `capabilities/introspection/graph_form.py` (формы argv) +
  `impact_digest.py` (сжатие `why`), порт `architecture_diagram`/`impact` +
  `ArchitectureDiagram`, адаптер поверх ожившего `graph`/`why`, капабилити
  `draw_architecture` (mermaid-ИСТОЧНИК) + `architecture_impact`, флаг
  `introspection.architecture_tools` (default OFF, НЕ включён).
  Гейты: pytest 6304 (база 6137, +167) · ruff · mypy src+tests · чистая БД
  `reindex`+`lint --strict` 0 violations · sync-check ok · doctor.
  Mutation: `graph_form` 68 мутантов / 100%, `impact_digest` 173 мутанта / 100%.
  Проверка на кусачесть: 8 саботажей (форма argv, ref-валидатор, membership-check,
  allowlist write-команд, сжатие, гейт флага, фолбэк, описание инструмента) — каждый
  покраснел на ожидаемых тестах.

## Ключевое, что нельзя потерять

- `graph` и `why` уже в allowlist, но **мёртвые** — до них не доходит ни один метод порта.
- `render_diagram` работает; капабилити отдаёт **mermaid-источник**, чтобы Боб мог и словами
  объяснить, и картинку приложить.
- 🔴 Write-команды beadloom **невыразимы** — read-only инвариант BOB-081 assert'ится тестом.
- Формы argv фиксированные (кортежи + membership-check), shell нигде.
- Флаг `introspection.architecture_tools` default OFF; включение после живого смоука.
- 🔴 Эпик закрывается **после живого смоука в Telegram** (схема реально пришла картинкой).
- 🔴 Живой факт для среза 2 и ревью: `graph --format c4 --level component --scope <ref>`
  печатает ОДИН заголовок `C4Container`, если `<ref>` — ЛИСТ графа (внутренности есть
  только у контейнера: `bob`, `bob-domain`). Отсюда честный фолбэк на форму узла +
  поле `form`/`requested` в `ArchitectureDiagram`, чтобы Боб не выдавал связи за
  внутренности. Проверено тестом на РЕАЛЬНОМ CLI (не на фейке).
- 🔴 `beadloom graph <несуществующий-ref>` = `graph LR` и rc=0 (пустая схема, не ошибка),
  `beadloom why <несуществующий>` пишет в stderr, stdout пуст → капабилити отвечают
  честным «не нашёл», а не пустой картинкой.
