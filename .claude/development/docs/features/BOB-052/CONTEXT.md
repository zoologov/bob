<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-052 — «Разрешение на привилегированное»

> **Status:** Approved
> **Created:** 2026-06-30

---

## Состояние

Не-авторизованный участник просит привилегированное (инструмент/внутрянка/owner-данные) → Боб спрашивает
owner (pending permission-request) → approve→исполнить (per-request/durable) / deny→мягкий отказ.
Авторизованные — без спроса. Реюз Authorizer (BOB-019), capability/tool-loop, паттерн approve (BOB-039).

## Ключевые решения (утверждены)

- **Детект:** семантический `PrivilegeJudge` (Tier-0, как `ResponseJudge`) — `PrivilegeNeed{needs_permission,
  kind: tool|internal|owner_data, what}`; только для не-авторизованного; общее знание (BOB-051) → обычный
  ответ.
- **Pending-состояние:** `PermissionRequest` (PENDING/APPROVED/DENIED/EXPIRED) + `SqlitePermissionRequestStore`
  (+ идемпотентная миграция, как coding_session).
- **Owner-решение:** 🔴 только `is_owner`. NL «да/нет/авторизуй» (консервативно, как BOB-042) + команды
  `/allow`/`/deny`/`/authorize`.
- **Грант:** per-request по умолчанию (разово исполнить); durable по явному «авторизуй» → `Authorizer.authorize`.
- **Исполнение на approve:** перепрогнать `request_text` с привилегией ТОЛЬКО для этого запроса (elevated
  одноразово) / durable обычным путём после authorize.
- **🔴 Отказоустойчивость:** сбой judge/стора/нотиса → тихо опускается, **безопасный дефолт = отказ** (не
  раскрывать), НЕ GUPPI-нотис.

## Стандарты (из CLAUDE.md §0.1)

- Python 3.12+, asyncio · DDD/Clean · frozen+slots, StrEnum · pytest · ruff · mypy --strict ·
  `.venv/bin/pytest` (uv run висит) · ≥80% · beadloom ci зелёный. Документы — русский; код — английский.

## 🔴 Инварианты (держать в голове)

- ТОЛЬКО owner approve/deny/authorize; не-owner не разрешает (даже себе).
- Привилегия — только для одобренного запроса (per-request) ИЛИ явный durable; без owner — ничего не
  раскрывается (безопасный дефолт = отказ).
- Внутрянка/owner-приват/инструменты неавторизованным — только через approve; BOB-051 (память публична) не
  ослаблена.
- Сбой флоу → тихо опускается, обычный ответ Боба цел (принцип «полный Боб»).
- Миграция идемпотентна; 🔴 бэкап data/bob.db перед живым рестартом.
- `.venv/bin/pytest`; ≥80%; ruff/mypy --strict/beadloom ci зелёные.

## Точки интеграции

- `src/bob/domain/` — `PermissionState`/`PermissionRequest`/`PrivilegeNeed` (новые), `PrivilegeJudge` порт,
  NL-предикаты approve/deny/authorize.
- `src/bob/application/usecases/` — `permission_flow.py` (детект→pending→нотис→решение→исполнение); провязка
  в `handle_message.py` (не-авторизованный путь); durable через `Authorizer.authorize`.
- `src/bob/infrastructure/persistence/` — `permission_request_store.py` (SQLite + миграция).
- `src/bob/infrastructure/llm/` — `LlmPrivilegeJudge` (Tier-0). Реюз Authorizer (BOB-019), capability
  registry/tool-loop, owner-нотис шов, per-person нить (BOB-045/051).
