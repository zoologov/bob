<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# PLAN: BOB-014 — «Отношения (multi-party) + обида/охлаждение» (T1.5)

> **Status:** Approved
> **Created:** 2026-06-23
> **Epic:** bob-8id (Тир 1 / T1.5)

---

## Беады (создаются ПОСЛЕ утверждения PLAN; под эпиком bob-8id)

| Беад | Роль | Описание | Зависит |
|------|------|----------|---------|
| `.1` | **dev** (RelationshipTracker) | `domain/personality/relationship.py` (4 измерения ∈[-1,1] + `apply_interaction(stance,mood,sentiment)`, дельты+дрейф) + `RelationshipStore` + Sqlite (per-sender) + влияние в `handle_message` (тон + порог уступчивости Negotiation) + апдейт после хода + персист. Тесты. | — |
| `.2` | **dev** (Обида/Sulk) | `domain/personality/sulk.py` (`SulkState`: вход при устойчивом критич. падении owner-отношения; затухание время+тепло; гарант. выход) + персист + **sulk-veto в governance** (проактив подавлен) + `voice.sulk_directive` (холодный реактив) + **GUPPI announce one-shot** + восстановление на reflect-тике. Anti-Exodus (память цела). | `.1` |
| `.3` | **test** | ≥80% + US-1..3 + guardrails (отношения в границах/дрейф; обида не по мелочи; **гарантированный выход**; идемпотентность; announce один раз; память цела) + регрессии (проактив/реактив/BOB-019). | `.1,.2` |
| `.4` | **review** | Гарантированный выход из обиды (нет вечной блокировки), не по мелочи, память не сбрасывается, отношения в границах, без регрессий. Read-only. | `.3` |
| `.5` | **tech-writer** | `architecture.md` (рус): RelationshipTracker, влияние, Sulk (governance/тон/GUPPI/восстановление), anti-Exodus. Gate. | `.4` |

## Волны (последовательно на одной ветке)

```
.1 (RelationshipTracker + влияние) → .2 (Обида/Sulk) → .3 test → .4 review → .5 tech-writer
```

- Dev-беады **последовательно** (фоновые агенты, общий tree). Ветка `features/BOB-014`, один PR.

## Критерии готовности

- [ ] Per-person отношения копятся и влияют на тон/уступчивость (в границах, дрейф).
- [ ] Обида: устойчивое падение → замолкание + GUPPI; не по мелочи; **гарантированно отходит**; память цела.
- [ ] «Как характер»; реактив/проактив/память/личность/BOB-019/тиринг не сломаны.
- [ ] cov ≥80%; `ruff`/`mypy --strict`/`beadloom ci` зелёные. **Тир 1 закрыт.**
