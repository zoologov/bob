---
title: presence
kind: feature
---

# presence

**Kind:** feature

Presence module («Bob's living rhythm») — the ритм-слой of human group presence: `ports.py` + pure domain (OutgoingActivity rolling window, ShareOfVoicePolicy soft ambient ceiling with focus-bypass, NaturalDelayPolicy human reply floor, ReactionBudget gentle like budget, RhythmConfig tunables) + `adapters/` (episodic-log OutgoingActivityStore). Domain-first slice BOB-066.2.3; inert behind the `presence.rhythm` flag until the epic ships.

**Source:** `src/bob/presence/`

## Public symbols

- `ArrivedMessage`
- `BacklogMessage`
- `BacklogScorer`
- `CatchUpPlan`
- `EpisodicOutgoingActivityStore`
- `LlmStalenessJudge`
- `NaturalDelayPolicy`
- `OutgoingActivity`
- `OutgoingActivityStore`
- `QueuedAmbient`
- `ReactionBudget`
- `RhythmConfig`
- `SeriesAction`
- `ShareOfVoicePolicy`
- `StalenessContext`
- `StalenessGate`
- `StalenessJudge`
- `StalenessOutcome`
- `StalenessReading`
- `build_staleness_user_prompt`
- `clamp_unit`
- `coalesce_stale`
- `decide_staleness`
- `delay_floor_seconds`
- `fair_target_share`
- `is_reentry`
- `nothing_arrived`
- `parse_staleness_reading`
- `plan_series_actions`
- `rank`
- `reaction_allowed`
- `score`
- `select_catchup`
- `share_damping`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [router](../features/router.md)
- **Used by**: [runtime](../services/runtime.md), [runtime-app](../features/runtime-app.md), [usecases](../features/usecases.md)

## Documentation

- [domains/presence/README.md](/docs/domains/presence/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="presence" :depth="1" height="60vh" />
</ClientOnly>

