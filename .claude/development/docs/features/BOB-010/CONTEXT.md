<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-010 — Эпик «Живой Боб»: человечность

> **Status:** Approved
> **Created:** 2026-06-20
> **Last updated:** 2026-06-20

---

## Цель

Боб (и все Бобы) — присутствующий компаньон со своим характером, настроением и историей отношений:
проактивность по «порыву», живая фактура, эволюция отношений/эмоций. Поведение — **выражение** Higher
Mind/памяти/heartbeat, не cron/шаблоны. *(Неизменна после утверждения.)*

## Ключевые ограничения

- Python 3.12+, asyncio, **DDD/гексагон**, `uv`, `mypy --strict`, `ruff`, покрытие ≥80%, TDD.
- **Инъекция `Clock` + seeded RNG** везде (детерминизм времени и стохастики).
- Всё состояние — **per-persona** (реплики наследуют). Реактивный чат (BOB-001..009) + authz/routing не ломать.
- Дёшево: порыв/governance — формула без LLM; Tier-0-гейт только при fire; Tier-1 — только на реплике.
- Время суток — **системное локальное** (через `Clock`).

## Стандарты кода

### Архитектура
- **DDD + Clean.** `domain` (чисто: urge/energy/relationship/fascination + порты) ← `application`
  (`ProactivityEngine`, governance, тик) ← `infrastructure` (стор, telegram, llm). Композиция в `app.py`.

### Тесты / качество
- TDD; pytest + asyncio + cov ≥80% (AAA); **ruff** + **mypy --strict** (src+tests); pytest-timeout net уже есть.

### Ограничения
- Без `Any`/`# type: ignore` без причины; без `print`/голого `except`; pathlib; параметризованный SQL;
  без `datetime.now()`/`random` без инъекции; без мутабельных дефолтов.

## Архитектурные решения

| Дата | Решение | Причина |
|------|---------|---------|
| 2026-06-20 | **Принцип:** человечность = состояние, управляющее тоном/содержанием/временем; НЕ трюки | анти-«бот»; выражение Higher Mind |
| 2026-06-20 | Проактив = **drive-модель** (порыв из состояния) + стохастика; rate-limit только потолок | живо/непредсказуемо, не механистично |
| 2026-06-20 | **Q1** `urge→p` логистическая; проверка на heartbeat-каденсе | fire редок за счёт модели |
| 2026-06-20 | **Q2** гейт = Tier-0, компоновка = тиринг | дёшево; качество где нужно |
| 2026-06-20 | **Q3** quiet ~23:00–09:00 локально + жёсткий пол; анти-спам = потолок | тюнинг live |
| 2026-06-20 | **Q4** relationship/fascination — аккумуляторы+дрейф (seed) | просто, тюнится |
| 2026-06-20 | **Q5** реакция vs ответ — эвристика+mood | живая невербалика |
| 2026-06-20 | Всё **per-persona**; `Clock`/seed инъекция | реплики Bobiverse + детерминизм |

## Связанные файлы

Открывать через `beadloom ctx`. Затрагиваются `application/proactivity`, `application/runtime/heartbeat`,
`domain/personality`, `infrastructure/{persistence,telegram,llm}`, `app.py`.

## Текущая фаза

- **Phase:** Planning → Development (Фаза 1 — проактивность)
- **Блокеры:** нет
