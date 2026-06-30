<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-049 — «Семантическое решение об отклике»

> **Created:** 2026-06-30

## Фокус

Заменить лестницу if/else-эвристик одним семантическим суждением (Боб понимает смысл -> reply/react/ignore)
+ эмодзи по смыслу + персист react/ignore + отказоустойчивость «полный Боб или GUPPI-нотис». Координатор,
автономно. Dev — ПОСЛЕДОВАТЕЛЬНО (гонка handle_message/app.py).

## Беады

| Беад | Роль | Статус | Зависит |
|------|------|--------|---------|
| `bob-yyg.1` | dev — шов суждения ResponseJudge + DecideResponse + Tier-0 | in_progress | — |
| `bob-yyg.2` | dev — провязка handle_message: ветвление + персист | blocked | .1 |
| `bob-yyg.3` | dev — отказоустойчивость (полный Боб или GUPPI-нотис) | blocked | .1,.2 |
| `bob-yyg.4` | test — US-1..5 + authz + отказоустойчивость | blocked | .1-.3 |
| `bob-yyg.5` | review — SECURITY | blocked | .4 |
| `bob-yyg.6` | tech-writer | blocked | .5 |

## Критический путь

```
.1 шов суждения → .2 провязка+персист → .3 отказоустойчивость → .4 test → .5 review → .6 tech-writer
```

## Инварианты (держать в голове)

- Решение по СМЫСЛУ, для любого собеседника (не is_owner); структурные сигналы — входы.
- 🔴 Authz BOB-019 ортогонально (гость — гостевой путь, owner-приват не утекает). Память: ход персистится
  при react/ignore.
- 🔴 Полный Боб или честный GUPPI-нотис (essential-сбой -> ретрай -> нотис; флейворы тихо опускаются;
  react/ignore-выбор != сбой).
- .venv/bin/pytest; >=80%; ruff/mypy --strict/beadloom ci зелёные.

## Прогресс

- 2026-06-30 — PRD/RFC/CONTEXT/PLAN утверждены (семантика + отказоустойчивость; принцип в ROADMAP #61);
  старый if/else-подход superseded; беады созданы; старт координатора.
