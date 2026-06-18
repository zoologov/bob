<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-001 — Личность Боба в Telegram

> **Status:** Approved
> **Created:** 2026-06-18
> **Last updated:** 2026-06-18

---

## Цель

Живой Боб с личностью в приватной Telegram-supergroup: стриминг-ответы с учётом настроения / вкусов /
памяти, текстовый Genesis при первом запуске, состояние переживает рестарт. Единый процесс (GUPPI).
*(Неизменна после утверждения.)*

## Ключевые ограничения

- Python 3.12+, asyncio, **единый процесс**, сборка `uv`.
- **DDD + Clean Architecture** (гексагон): `infrastructure → application → domain`; domain без I/O;
  композиция только в `app.py`.
- SQLite (WAL) + **FTS5**; без RAG/эмбеддингов в P0 (порт `MemoryRecall` для замены keyword→vector).
- LLM только через **OpenAI-совместимый** клиент; Tier 0 — локальный MLX, Tier 1 — Qwen API.
- Приватность (VISION §7.1): личность/память по умолчанию → Tier 0; эскалация в Tier 1 только с
  **редакцией** контекста.
- Заморожено вне P0: облик/FLUX (P1), реплики/оркестрация (P2), голос/железо.

## Стандарты кода

### Язык и окружение
- **Python 3.12+** (type hints, `str | None`), `uv` (venv + sync).

### Архитектура
- **DDD + Clean Architecture (гексагон).** Слои: `domain` (чистая логика/модели) ← `application`
  (use-cases, GUPPI-рантайм, router) ← `infrastructure` (адаптеры: Telegram/LLM/SQLite/config).
  Зависимости направлены только внутрь. Порты-протоколы объявлены в `domain`, реализованы в
  `infrastructure`, связываются в `app.py`. **Это не CLI-тула** — никакого «CLI → Core → Storage».

### Методологии
| Методология | Применение |
|-------------|-----------|
| TDD | Red → Green → Refactor |
| Clean Code | snake_case, SRP, DRY, KISS |
| Гексагональная (порты/адаптеры) | домен изолирован от транспорта/провайдера/хранилища |

### Тесты
- **pytest** + pytest-asyncio + pytest-cov, AAA, покрытие **≥80%**.

### Качество
- **ruff** (lint + format), **mypy --strict**.

### Ограничения
- Без `Any` / `# type: ignore` без причины; без `print()` / `breakpoint()` — логирование;
  без голого `except:` — только конкретные исключения; **pathlib**, не `os.path`;
  **параметризованный SQL** (`?`), не f-strings; `yaml.safe_load`; без `datetime.now()` без инъекции
  `Clock`; без мутабельных дефолтов.

## Архитектурные решения

| Дата | Решение | Причина |
|------|---------|---------|
| 2026-06-18 | DDD-гексагон; GUPPI = application + infrastructure | личность платформонезависима, тестируемость |
| 2026-06-18 | LLMRouter поверх OpenAI-совместимого провайдера | флип «локально ↔ API» = смена адаптера, не переписывание |
| 2026-06-18 | Ответ пользователю: Tier 1 (Qwen) + редакция, fallback Tier 0 (Q2) | баланс качества и приватности |
| 2026-06-18 | Long-polling в P0 (Q3) | проще, нет публичного эндпоинта |
| 2026-06-18 | FTS5 вместо FAISS; порт `MemoryRecall` | достаточно на MVP; экономия RAM/сложности |
| 2026-06-18 | Инъекция `Clock` | детерминизм тестов; запрет `datetime.now()` |

## Связанные файлы

Гринфилд — структура создаётся в этом эпике. Узлы открывать через `beadloom ctx <ref-id>` по мере
появления; пути не хардкодить.

## Текущая фаза

- **Phase:** Planning → Development
- **Текущий беад:** назначится после создания DAG
- **Блокеры:** нет
