---
title: proactivity
kind: feature
---

# proactivity

**Kind:** feature

Proactivity module («Bob's background life») — the full vertical capability in one place: `ports.py` + pure domain (drive-model urge/governance/social-energy, goals graph, self-improvement rules — the RuleModulators value they build lives in `kernel`, BOB-113), `usecases/` (engine/tick, plan/pursue goals, detect-patterns/announce-rules), and `adapters/` (proactivity/goal/self-improvement stores + live read-seams). Domain-first slice BOB-062.3.

**Source:** `src/bob/proactivity/`

## Public symbols

- `ActiveRulesReader`
- `AnnounceProposedRules`
- `AnnounceRestart`
- `AnnounceStatus`
- `DetectPatterns`
- `EpisodeWriter`
- `Goal`
- `GoalGraph`
- `GoalOrigin`
- `GoalState`
- `GoalStore`
- `GoalStoreLike`
- `Governance`
- `GovernanceConfig`
- `HistorySource`
- `ImprovementRule`
- `ImprovementSignals`
- `KvRestartMarkerStore`
- `Lever`
- `LlmPatternDetector`
- `LlmPlanner`
- `PatternDetector`
- `PlanGoal`
- `PlanResult`
- `Planner`
- `ProactiveDecider`
- `ProactiveHistory`
- `ProactiveRunner`
- `ProactiveTick`
- `ProactiveWindowCounter`
- `ProactivityEngine`
- `ProactivityState`
- `ProactivityStore`
- `ProactivityStoreLike`
- `ProgressWindowCounter`
- `ProposalDefect`
- `PursueGoalsTick`
- `PursuitStore`
- `RecordOwnerActivity`
- `ReflectionSalienceSource`
- `RepoProactivitySources`
- `RestartMarkerStore`
- `RestartMoment`
- `RestartNotifier`
- `RuleAnnounceGateway`
- `RuleAnnounceStore`
- `RuleLoader`
- `RuleOrigin`
- `RuleState`
- `SafeDispatcher`
- `SelfImprovementStore`
- `ShareCeiling`
- `SignalSource`
- `SocialEnergy`
- `SqliteGoalStore`
- `SqliteProactivityStore`
- `SqliteSelfImprovementStore`
- `SulkSource`
- `Task`
- `TaskState`
- `UrgeModel`
- `active_rules`
- `announce_status`
- `blocked_reason`
- `build_modulators`
- `can_transition`
- `can_transition_task`
- `clamp_magnitude`
- `external_agency_tasks`
- `is_actionable_proposal`
- `is_duplicate_rule`
- `is_goal_complete`
- `is_undelivered_proposal`
- `next_safe_task`
- `next_to_announce`
- `proposal_defect`
- `proposal_message`
- `proposal_speech`
- `ready_tasks`
- `restart_voice`
- `rules_for_lever`
- `unactionable_reason`
- `urge_to_probability`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md), [conversation](../features/conversation.md), [memory](../features/memory.md), [personality](../features/personality.md), [router](../features/router.md)
- **Used by**: [runtime](../services/runtime.md), [telegram](../other/telegram.md), [usecases](../features/usecases.md)

## Documentation

- [domains/proactivity/README.md](/docs/domains/proactivity/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="proactivity" :depth="1" height="60vh" />
</ClientOnly>

