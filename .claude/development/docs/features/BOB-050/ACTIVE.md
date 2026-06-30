<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-050 — «Восприятие реакций на сообщения Боба»

> **Created:** 2026-06-30

## Фокус

Боб чувствует, как восприняли его сообщения (реакции/снятие, по смыслу). Транспорт message_reaction +
bob_message_id-связь + шов ReactionJudge + эффекты + изредка-вслух. Декоративно (сбой тихо опускается).
Координатор, автономно. Dev — ПОСЛЕДОВАТЕЛЬНО (гонка app.py/handle_message).

## Беады

| Беад | Роль | Статус | Зависит |
|------|------|--------|---------|
| `bob-761.1` | dev — транспорт + BobMessageReaction + bob_message_id | in_progress | — |
| `bob-761.2` | dev — ReactionJudge + PerceiveReaction (эффекты) | blocked | .1 |
| `bob-761.3` | dev — изредка вслух | blocked | .1,.2 |
| `bob-761.4` | test — US-1..6 + authz + декоративность | blocked | .1-.3 |
| `bob-761.5` | review — SECURITY | blocked | .4 |
| `bob-761.6` | tech-writer | blocked | .5 |

## Критический путь

```
.1 транспорт+связь → .2 шов+эффекты → .3 изредка-вслух → .4 test → .5 review → .6 tech-writer
```

## Инварианты (держать в голове)

- Смысл реакции семантически, НЕ emoji->таблица; эффекты bounded (без качелей).
- 🔴 Декоративно: сбой восприятия тихо опускается, НИКОГДА не GUPPI-нотис, ответы Боба целы.
- 🔴 Authz BOB-019 (гость per-person, owner-приват не утекает); память per-person.
- Миграция bob_message_id идемпотентна; 🔴 бэкап data/bob.db перед живым рестартом; 🔴 verify доставки вживую.
- .venv/bin/pytest; >=80%; ruff/mypy --strict/beadloom ci зелёные.

## Прогресс

- 2026-06-30 — PRD/RFC/CONTEXT/PLAN утверждены (зеркало BOB-049); беады созданы; старт координатора.
