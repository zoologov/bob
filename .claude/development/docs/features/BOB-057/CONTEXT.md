<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-057 — «Боб знает, чего не знает» (эпистемическая проверка)

> **Status:** Approved
> **Created:** 2026-07-01
> **PRD/RFC:** `./PRD.md` · `./RFC.md`

---

## Суть (одним абзацем)

Перед ответом Боб делает метакогнитивный шаг: Tier-0 `VolatilityJudge` (консервативный) решает, зависит ли
ответ от свежего волатильного факта. Если да → живая адресная интерим-реплика → ОДИН прямой `web_search`
(не через tool-loop → не гейт BOB-052) → находка вплетается в контекст генерации (факты+тон в голосе Боба).
Если нет → обычный ответ, ноль задержки. Сбой/пусто → честный хедж. Всё декоративно.

## Ключевые решения (утв. в PRD/RFC)

1. **Точка проверки:** pre-answer single-pass (судья ДО генерации, одна Tier-1-генерация с находкой).
2. **Прямой web_search (не tool-loop) → НЕ гейт BOB-052** — internal public-verify, работает для всех (Лёша/
   гость); поиск публичный, утечки приватного нет.
3. **Интерим-реплика:** живая Tier-0-генерация из `topic`+имя, fallback на seeded-фразы BOB-055.
4. **Сбой/пусто:** честный эпистемический хедж; судья/интерим декоративны.
5. **Провайдер v1 — Qwen web_search** (латентность прикрыта интеримом+хеджем+коротким таймаутом); Tavily —
   апгрейд латентности потом (за тем же портом `WebSearchProvider`), в ROADMAP.

## Архитектура (где что лежит)

- **domain:** `domain/personality/volatility_judgment.py` — `VolatilityVerdict{needs_check, query, topic}`,
  `VolatilityContext`, `VolatilityJudge` (Protocol), `parse_volatility_verdict` (стиль `response_judgment.py`).
- **application:** verify-шаг в `HandleMessage._compose_reply` (судья → интерим → один
  `provider.search(query)` → grounded/hedge-заметка → генерация); инъекция `VolatilityJudge` +
  `WebSearchProvider` (optional) в `HandleMessage`; живая интерим-реплика (расширение
  `GatewayProgressAnnouncer` контекстным режимом или лёгкая Tier-0-генерация). Конфиг `verify.*`.
- **infrastructure:** `infrastructure/llm/volatility_judge.py` — `LlmVolatilityJudge` (Tier-0, новый
  `TaskType.VOLATILITY_JUDGE`, консервативный промпт, raise-on-failure); интерим-генерация (Tier-0).

## 🔴 Инварианты (НЕ нарушать)

- **US-2 не зануда:** судья консервативный — `needs_check=True` ТОЛЬКО если факт реально волатилен И меняет
  ответ; болтовня/мнения/шутки/стабильные факты/память Боба → `False`. Тест-инвариант на набор «не
  проверять». По умолчанию — не проверять.
- **US-3 не 5 минут:** один поиск (не петля), короткий `verify.timeout_seconds`, интерим-реплика сразу,
  hedge при затяжке.
- **US-5 не привилегия:** прямой internal web_search (не `registry.dispatch`) — не триггерит BOB-052;
  раскрывает только публичное. 🔴 BOB-051/052 на пользовательских tool-запросах НЕ ослабляются; внутрянка/
  owner-данные по-прежнему гейтятся.
- **US-6 честность (инвариант BOB-053):** сбой/пусто → честный хедж, НЕ уверенная устаревшая цифра под
  видом факта, НЕ выдумка.
- **Декоративность:** сбой судьи → `needs_check=False` (обычный ответ); сбой интерима → seeded fallback/
  молчание; ход/ответ никогда не ломаются и не блокируются.
- **Single-pass:** одна Tier-1-генерация (не draft→revise).
- **DDD:** domain ← application ← infrastructure; композиция в `app.py`/`HandleMessage`; seeded-RNG/Clock
  инъектируются (детерминизм тестов); судья raise → caller решает (safe-default).

## Стандарты кода (из CLAUDE.md §0.1)

- Python **3.12+**, asyncio; **DDD + Clean Architecture**. `ruff`, `mypy --strict`; frozen+slots, StrEnum,
  без `Any`/`# type: ignore` без причины. TDD; покрытие ≥ 80% (`mypy src tests`). Без `print`/`breakpoint`,
  bare `except`, `import *`, mutable-default. Русские литералы → per-file-ignore RUF001/002/003. Реплики/
  хедж/интерим — на русском, в голосе Боба, живые.

## Реюз / прецеденты

- `response_judgment.py` + `LlmResponseJudge` — образец судьи (домен value+parser+Protocol; инфра Tier-0
  prompt-builder+parser+raise, `TaskType`). Зеркалить.
- `privilege_judge.py` (BOB-052) — ещё образец Tier-0-судьи.
- `WebSearchProvider`/`build_web_search_provider` (BOB-053/055 стриминг) — прямой вызов для verify.
- `GatewayProgressAnnouncer` (BOB-055) — база интерим-реплики (расширяем контекстом).
- `_safe_addon` (BOB-050) — декоративный тихий drop. `_compose_reply`/`_reply_with_tools` — точка вставки.

## Связи

BOB-053/055 (web_search, реюз) · BOB-054 (read_url) · BOB-049/052 (Tier-0-судьи) · BOB-050 (_safe_addon) ·
BOB-051/052 (authz — не ослаблять) · ROADMAP #10 (честный нотис) · метакогниция:
`bob-consciousness-markers-lens` + будущий эпик «Самомодель и метакогниция» · перед BOB-056 (web_research).
