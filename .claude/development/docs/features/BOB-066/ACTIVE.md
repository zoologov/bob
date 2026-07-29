<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: bob-vol.9.1 — Срез 2.6-dev (такт разглашения + кредит доверия)

## Фокус
Пласт 4 RFC: такт разглашения (visibility-провенанс + may_surface + tactful_withhold)
+ кредит доверия (endorsement seed). INV-7: owner recall byte-identical; гость-фильтр латентен.

## План (TDD)
- [ ] social/disclosure.py — may_surface(visibility, trust) + visibility_for_scope(is_group) [mutation]
- [ ] social/endorsement.py — detected_endorsement(owner_text) + owner_endorsed_sender [mutation on detected]
- [ ] relationship.endorsed_seed(rel|None, sender_id) [mutation]
- [ ] voice.tactful_withhold_directive()
- [ ] visibility migration (schema.sql + guarded ALTER, NULL=public)
- [ ] write-side visibility (save_episode/save_fact + _persist + extract_facts)
- [ ] recall filter (may_surface в handle; visibility через fts_recall + vector_store)
- [ ] endorsement seed interception (guarded: rel None + guest + owner endorsement)
- [ ] BDD .feature (owner_private не всплывает гостю; public всем; tactful vs dry; endorsed warm start)
- [ ] mutation ≥85% на 3 ядрах

## Прогресс
ГОТОВО (dev): все пункты плана реализованы, TDD+BDD+mutation зелёные.
- Чистые ядра (100% cov, mutation): may_surface (1 эквив-мутант), detected_endorsement (0),
  endorsed_seed (0). owner_endorsed_sender: killed 6, 5/8 эквивалентны (maxsplit ≠ [0]).
- Миграция visibility (schema + guarded ALTER, NULL=public), write-side, recall-фильтр
  (owner TRUSTED байт-в-байт), visibility через fts_recall+vector_store.
- BDD: 7 сценариев disclosure_tact.feature зелёные.
- Gate: pytest 3702✓ · mypy full 0 · ruff ✓ · reindex --full + lint --strict EXIT 0.
- sync-check exit 2 (домен-READMEs stale) → ВОЛНА tech-writer (по DoD).

## DEFERRED (live-wiring, латентно — гости не live; сообщено)
- endorsement-seed перехват в handle: нужен owner_id на seam load_relationship — отложено.
- tactful_withhold в guest-compose: нужен guest owner_data seam — отложено (директива готова).
