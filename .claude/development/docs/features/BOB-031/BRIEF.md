<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-031 — Маршрутизация навыков самоинтроспекции (grounding + листинг задач)

> **Status:** Approved
> **Created:** 2026-06-25
> **Type:** bug · поверх BOB-017 Phase A · эпик `bob-031`

---

## Проблема

BOB-017 Phase A отгрузил навыки, но реальная маршрутизация к `bd`/`beadloom` имеет дыры (test/review
гоняли FAKE-интроспектор, реальные CLI не прогоняли):

1. **`inspect_architecture` не grounded на свободный текст.** `architecture_context(ref)` зовёт
   `beadloom ctx <ref>` — нужен точный **ref-id узла**. Естественный вопрос («как устроена память») →
   `beadloom ctx memory` = **пусто** (проверено живьём: `architecture_context("memory") == ''`). Боб
   отвечает из общих знаний, **не из beadloom** — звучит правдоподобно, но grounding (смысл Phase A)
   не происходит. `beadloom search "memory"` свободный текст берёт идеально.
2. **`list_work` не показывает закрытые/недавние/все.** Умеет только `bd ready` (сейчас пусто — все
   беады закрыты) + `bd show <id>`. На «какие задачи закрыты / в работе / история» → пусто. + мусор
   в выводе («💡 Tip: install plugin…»).
3. **Повтор (следствие).** Два вопроса о задачах бьют в один пустой `bd ready` → одинаковый рифф
   «Пусто». Anti-repeat не догоняет (одинаковый пустой вход → одинаковый ответ). Чинится сам, когда
   навык даёт реальные разные данные.

## Решение

1. **`inspect_architecture` / `architecture_context`:** свободный текст → `beadloom search`; точный
   ref-id → `beadloom ctx` (+ при желании `graph`/`why`). Эвристика «это ref-id?» детерминированная;
   **fallback `ctx`→`search` при пустом результате**, чтобы естественные вопросы всегда заземлялись.
2. **`list_work` / `list_tasks`:** добавить `bd list` (status `closed`/`open`/`in_progress`/all) в
   read-allowlist `_BD_SUBCOMMANDS`; маршрутизация запроса: id → `show`; «закрытые/недавние/в работе/
   все/история» (или пустой) → подходящий `bd list`/`ready`. **Денойз** служебного «Tip»-хвоста.
3. **Интеграционный тест на реальных `bd`/`beadloom`** (не только fake): `inspect_architecture` на
   свободный текст возвращает непустой grounded-результат; `list_work` показывает закрытые задачи.
   Проверить порог anti-repeat на одинаковых ответах (отметить, если требует отдельного фикса).

**Без изменений:** приват-инвариант (`PrivacyGuard`), read-only/`exec`-без-shell, границы стадии
(навыки НЕ в автономном `goals.safe_capabilities`). Только расширяем read-allowlist на `bd list`.

## Беады (создаются ПОСЛЕ утверждения BRIEF)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** | `architecture_context` свободный текст→`beadloom search` (ref-id→`ctx`, fallback на пустом); `list_tasks` + `bd list` в allowlist + маршрутизация closed/all/in_progress + денойз «Tip». Юнит-тесты с fake. | — |
| `.2` | **test** | ≥80% + **интеграционный тест на реальных `bd`/`beadloom`** (grounded свободный текст; листинг закрытых) + честный «не нашёл» + приват-инвариант/границы целы + регрессии (BOB-017 навыки/tool-loop). Проверить порог anti-repeat. `.venv/bin/pytest`. | `.1` |
| `.3` | **review** | Read-only/приват-инвариант/границы стадии целы (только read-allowlist расширен на `bd list`); grounding реально работает; без регрессий; чистота DDD. Read-only. | `.2` |
| `.4` | **tech-writer** | `architecture.md` (рус): обновить маршрутизацию навыков (search для свободного текста, `bd list` для закрытых). Gate. | `.3` |

## Критерии готовности

- [ ] `inspect_architecture` на естественный вопрос возвращает **grounded** результат из beadloom (не пусто).
- [ ] `list_work` показывает закрытые/недавние/в работе задачи; «Tip»-шум убран; повтор на задачах исчез.
- [ ] Интеграционный тест на реальных CLI зелёный; приват-инвариант/read-only/границы не ослаблены.
- [ ] cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные; BOB-017 навыки/tool-loop не сломаны.
