<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# BRIEF: BOB-062.5 — «Срез social → src/bob/social/» (Фаза 3, срез 5/8)

> **Status:** Approved
> **Created:** 2026-07-28
> **Type:** feature · срез эпика BOB-062 · BOB-Issues #14
> **Родитель:** `bob-8r4.5` · Контекст: эпик `RFC/CONTEXT` + прецеденты .1–.4 + генератор правил (.4)

---

## Проблема

Социальная идентичность + авторизация («Боб различает людей — owner/гости, ведёт первое впечатление и
отношения на каждого, проверяет привилегии») расколота: `domain/permission/` + `domain/personality/
{interlocutor,first_impression,relationship,sulk}` + `application/authz/` + `usecases/{permission_*,
*_sources,run_genesis}` + persistence-сторы + `llm/privilege_judge` + `ports/social` + части
`ports/personality`. Собираем в `src/bob/social/`. Это ровно тот модуль, где живёт мультиперсональная
идентичность из аудита (аудит команды 2026-07-28 — cross-sender контекст здоров).

## 🔴 Решения (развилки — утв. owner / по данным разведки)

1. **Цикл personality↔social — Вариант B (утв. owner):** `interlocutor.py` **едет в social** (концептуально
   верно — «кто этот человек» = ядро social). Разорвать одно runtime-ребро: `domain/personality/voice.py:37`
   больше НЕ импортит `InterlocutorKind` — получает kind как **уже-вычисленное значение** (параметр/через
   ExpressionPlan), behavior-preserving. Итог: social владеет identity+relationships целиком; зависит от
   personality однонаправленно (`relationship→negotiation.Stance` — отношения окрашены стилем торга). Цикла нет.
2. **run_genesis → в social** (рекомендация, менее спорно): по зависимостям чист — только `SoulStore`
   (social-порт) + `router` (shared app), **0 импортов personality**. «Рождение идентичности» ложится в social.
3. **privileged_fulfiller → ОСТАЁТСЯ в `application/usecases/`** (НЕ в social-vertical): cross-domain
   оркестратор, тянет `capabilities.usecases.tool_loop` (RUNTIME) — это application-оркестрация (как
   handle_message), не social-домен. Избегаем первого vertical↔vertical runtime-стыка. Его импорты social-
   типов (если есть) правятся здесь.

## Решение (атомарный переезд, behavior-preserving) — ~24 файла

Целевая структура:
```
src/bob/social/
  ports.py            # layer=domain ← domain/ports/social.py (Allowlist/SoulStore) + из ports/personality.py
                      #   (First/Relationship/Sulk Store) + PrivilegeJudge (из permission/privilege.py)
  __init__.py         # layer=domain
  interlocutor.py first_impression.py relationship.py sulk.py  ← из domain/personality/ (layer=domain)
  permission/         # layer=domain ← domain/permission/ (entities/intent/privilege/state)
  usecases/           # layer=application ← application/authz/ (authorizer/sender_perception/reactor_perception)
                      #   + permission_flow/permission_execution/first_impression_sources/relationship_sources/
                      #   sulk_sources/run_genesis
  adapters/           # layer=infrastructure ← persistence/{first_impression,relationship,sulk,allowlist,
                      #   permission_request,soul}_store + llm/privilege_judge
```

**ОСТАЮТСЯ (не social):** `ports/personality.py` — MessageReactor/ReflectionReader/Fascination/NotableReaction/
ZoneClassifier (реакция/рефлексия ≠ social). `reaction_judge.py` (personality). `privileged_fulfiller.py`
(application-оркестратор). kernel (sqlite_repo/schema/vector_store) — вариант C. `perceive_reaction.py` (personality).

**🔴 Kernel (вариант C — подтверждён):** social-сторы (first_impression/relationship/sulk/permission_request)
через `connection()` seam; allowlist — kv; soul_store — файловый (soul_dir). Обратной kernel→social нет
(sqlite_repo `get/set_relationship` — legacy owner-blob, ДРУГОЙ концепт). schema-таблицы остаются в kernel.

**Внешние прод-правки:** `app.py` (authz/permission/genesis wiring — ~15 строк), `domain/ports/__init__.py`
(шим: убрать First/Relationship/Sulk из personality-блока, расширить social), `domain/ports/personality.py`
(удалить 3 порта + их TC-импорты), `handle_message.py` (импорт-пути interlocutor/relationship/sulk типов —
методы SocialContext ОСТАЮТСЯ до .6), `decide_response.py`/`perceive_reaction.py` (TC/runtime social-типы),
`persistence/__init__.py`. 🔴 `voice.py` — разрыв ребра (решение 1). guppi/multibot — только docstring.
Тесты (~28) — импорты; grep строковых литералов путей после git mv.

## Беады (роль-суб-беады под `bob-8r4.5`)

- **`.1` dev** — переезд social (~24ф git mv вкл. interlocutor + разрыв `voice→InterlocutorKind` behavior-
  preserving; run_genesis в social; privileged_fulfiller НЕ трогать кроме импортов; kernel не трогать;
  переписать app.py/ports-шим/ports-personality/handle_message/decide_response/perceive_reaction/re-export +
  ~28 тестов; аннотации feature=social+layer=; узел module-vertical). pytest/ruff/mypy зелёные.
- **`.2` dev** — правила: добавить узел `social` в services.yml (удалить permission/authz узлы), перезапустить
  `scripts/gen_boundary_rules.py` (генерит social-правила + добавляет social в inward всех модулей). Note-блок
  legalized: social→personality (negotiation.Stance/mood — публичная domain-поверхность), social-usecases→
  router (shared), ports-шим. 🔴 Проверить цикл personality↔social РАЗОРВАН (no-dependency-cycles зелёный).
  `beadloom lint --strict` зелёный (reindex --full).
- **`.3` test** — pytest + social-инварианты (owner/guest classify, restricted-режим гостя, first-impression
  на нового, relationship apply_interaction, sulk observe/recover анти-Exodus, privilege двойной-гейт,
  allowlist authz, genesis first-boot) + механика правил (social↔personality изоляция) + beadloom ci.
- **`.4` review** — переезд + 🔴 разрыв цикла чист (voice-fix behavior-preserving) + границы + genesis/
  privileged_fulfiller размещение обоснованы; вердикт для .6 (personality+conversation — что осталось).
- **`.5` tech-writer** — SPEC/DOC social; закрыть #14; Gate (sync-update bob + setup-rules --refresh).

## Критерии приёмки

- `src/bob/social/` собран (identity/relationships/permission/authz/genesis); interlocutor в social,
  цикл personality↔social разорван (voice получает kind параметром); privileged_fulfiller остался в application.
- `pytest` зелёный (поведение идентично); social-инварианты целы; `ruff`/`mypy --strict` зелёные.
- `beadloom ci` зелёный (no-dependency-cycles PASS); legalized refs помечены. BOB-Issues #14 закрыт.

## Связи

Эпик BOB-062, срез 5/8. 🔴 kernel-split → .7; personality+conversation (+handle_message #9) → .6 (там
цикл personality↔conversation — аналог этого разреза). Следующий: `.6` (`bob-8r4.6`).
