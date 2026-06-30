<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# CONTEXT: BOB-051 — «Единая публичная память закрытой группы»

> **Status:** Approved
> **Created:** 2026-06-30

---

## Состояние

Один флаг `is_guest` (BOB-019 `Trust.GUEST`) гейтит и память, и привилегии. Расцепить: память
(recall/история/голос/fact-extraction) → единая/публичная для всех в закрытой группе; привилегии
(capabilities/внутрянка/owner-данные) → остаются гейтом (BOB-052/authz). Боб — один разум.

## Ключевые решения (утверждены)

- **Снять `_scoped_recall` per-person скоуп** (`handle_message` ~2302) → recall единый для любого собеседника.
- **Не-owner получает recall + per-person историю + нормальный голос** (снять stranger-voice/гостевой
  memory-урез BOB-019); fact-extraction со всех групповых ходов.
- **🔴 ОСТАЁТСЯ гейтом:** capabilities/tool-loop, owner inner-life add-ons (`leak_inner_life`/callback/
  fascination — внутрянка), owner-команды/данные (`/code`/`/goals`/config). `is_guest` = флаг ПРИВИЛЕГИЙ,
  не памяти.
- Per-person нить/атрибуция (BOB-049/050) — цела.
- `recalled_excluding_reflections` (BOB-033) остаётся (рефлексии не копируются дословно).

## Стандарты (из CLAUDE.md §0.1)

- Python 3.12+, asyncio · DDD/Clean · frozen+slots · pytest · ruff · mypy --strict · `.venv/bin/pytest`
  (uv run висит) · ≥80% · beadloom ci зелёный. Документы — на русском. Код/докстринги — на английском.

## 🔴 Инварианты (держать в голове)

- Память единая/публичная в группе; не-owner получает recall+историю+нормальный голос.
- 🔴 Привилегии целы: не-owner НЕ получает tools/inner-life/owner-команды без авторизации/разрешения.
  Тест-инвариант: не-owner → память+голос ЕСТЬ; tool-loop НЕТ, inner-life НЕТ, `/code`/`/goals` отказ.
- Per-person нить/атрибуция/реакции (BOB-045/049/050) не сломаны.
- `.venv/bin/pytest`; ≥80%; ruff/mypy --strict/beadloom ci зелёные.

## Точки интеграции

- `src/bob/application/usecases/handle_message.py` — `_scoped_recall` (~2302, убрать скоуп); гостевой
  memory-блок (~1228-1383: recall/history/stranger-voice/fact-extraction ~1381); расцепить memory- от
  привилегий-использований `is_guest`.
- `src/bob/domain/personality/` — `stranger_directive` (не добавлять для участников группы).
- Реюз BOB-019 (`Interlocutor`/`Trust`/authz), BOB-045 (per-person нить).
