<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1 -->

# ACTIVE: BOB-066 — между срезами

## Последний завершённый срез
**W.4-dev (bob-vol.12.4) — ЗАКРЫТ.** EQ live-врезка (Пласт 4), обе за нестед-флагами, OFF=byte-identical:
- **Кредит доверия** (`presence.endorsement.enabled`): `endorsement_seed` (pure, social/endorsement.py) +
  `EndorsementSeeder` (application) источает owner-turns из shared-thread по `owner_id`; врезка в handle()
  после replay истории re-bind `relationship` тёплым seed на ПЕРВОМ контакте гостя, за которого владелец
  поручился по имени. Turn-local (latent, не персист).
- **Такт разглашения** (`presence.tact.enabled`): `disclosure_refusal_directive` (pure, voice.py) +
  `DisclosureGuard` переиспользует PrivilegeJudge port; `withhold_directive` threaded в compose+guard
  (turn-constant, как room_tone). 🔴 Privilege GATE не тронут — только ГОЛОС отказа.
- Cohesion: `_prepare_eq_live` собирает обе врезки + is_guest в ОДИН statement → handle() остался 50
  стейтментов (PLR0915 без noqa). Нет нового цикла (argument-shaped, lint --strict EXIT 0).
- Тесты +39 (unit/collaborator/wiring/handle-integration/BDD `eq_live_wiring.feature`). Мутация:
  endorsement_seed 27/27, disclosure_refusal 2/2 = 100%. 3914 зелёных, cov 99%, mypy FULL 0, ruff 0.
- NOTE: `owner_endorsed_sender` substring-match (slice-2.6 review flag) НЕ трогал — pre-existing + latent;
  2 выживших мутанта на нём — ЭКВИВАЛЕНТНЫЕ (split maxsplit инвариантен к `[0]`).
- architecture.md + domains/{social,personality}/README.md doc-stale → tech-writer волна.

## Следующий фокус
**W-test (bob-vol.12.5)** — интеграция + INV под флагами ON — разблокирован.

## Инварианты-напоминание
INV-1 фокус минует любой потолок/бюджет (never dropped). Флаги OFF = byte-identical. INV-7 приватность
скоупа (privilege GATE цел, меняется только VOICE).
