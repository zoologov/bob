---
title: proactivity
kind: feature
---

# proactivity

**Kind:** feature

Proactivity module («Bob's background life») — the full vertical capability in one place: `ports.py` + pure domain (drive-model urge/governance/social-energy, goals graph, self-improvement rules), `usecases/` (engine/tick, plan/pursue goals, detect-patterns/announce-rules), and `adapters/` (proactivity/goal/self-improvement stores + live read-seams). Domain-first slice BOB-062.3.

**Source:** `src/bob/proactivity/`

## Public symbols

- `ActiveRulesReader`
- `AnnounceProposedRules`
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
- `PursueGoalsTick`
- `PursuitStore`
- `RecordOwnerActivity`
- `ReflectionSalienceSource`
- `RepoProactivitySources`
- `RuleAnnounceGateway`
- `RuleLoader`
- `RuleModulators`
- `RuleOrigin`
- `RuleReader`
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
- `blocked_reason`
- `build_modulators`
- `can_transition`
- `can_transition_task`
- `clamp_magnitude`
- `external_agency_tasks`
- `is_duplicate_rule`
- `is_goal_complete`
- `next_safe_task`
- `ready_tasks`
- `rules_for_lever`
- `urge_to_probability`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [conversation](../features/conversation.md), [memory](../features/memory.md), [personality](../features/personality.md), [router](../features/router.md)
- **Used by**: [runtime](../services/runtime.md), [telegram](../other/telegram.md), [usecases](../features/usecases.md)

## Documentation

- [domains/proactivity/README.md](/docs/domains/proactivity/README.md)

## Diagram

```mermaid
C4Container
    System_Boundary(bob_boundary, "Bob") {
        Container(bob_application, "Bob Application", "", "GUPPI orchestration: AgentRuntime + AsyncEventBus, LLMRouter (tier routing + privacy redaction), use-cases (HandleMessage, RunGenesis, UpdateMoodFromText), resilient heartbeat ticks (retry/backoff), the Authorizer access policy and the capability seam (CapabilityRegistry + ToolLoop + recall_memory). Depends on domain via ports; never imports infrastructure.")
        Container(bob_domain, "Bob Domain", "", "Domain layer umbrella: the seven module-vertical bounded contexts (personality, conversation, memory, proactivity, coding, capabilities, social) plus the shared 'kernel' (infra-neutral cross-module contracts). Pure logic + Protocol definitions; no I/O, no LLM, no transport.")
        Container(bob_infrastructure, "Bob Infrastructure", "", "Port adapters: aiogram Telegram gateway (long-polling + authz gate, native draft streaming, Rich Messages, markdown‹-›RichMessage, topic-thread reply pinning), MultiBotGateway (BotRegistry + cross-bot dedup + central identity/scope router) and the GuppiHandler gatekeeper (visible reject + owner commands), OpenAI-compatible LLM provider (Tier 0/1 + tool-calling), SQLite+FTS5 persistence, KvAllowlistStore and SoulStore, two-bot layered config loader.")
        Container(runtime, "Runtime", "", "Composition root ('src/bob/runtime/' package + the thin 'app.py' shim) — the only layer allowed to wire all layers + all vertical modules at once: 'config.py' loads layered config (incl. '_REPO_ROOT'), 'wiring/*' build infrastructure adapters + compose application policy/use-cases per bounded context, 'composition.py' ('build_application' + 'Application') subscribes handlers to the EventBus and registers ticks + Telegram polling, 'clock.py' provides 'SystemClock', and 'main.py' runs Genesis once and starts the process.")
    }
    Rel(bob_application, bob_domain, "depends_on")
    Rel(bob_infrastructure, bob_application, "depends_on")
    Rel(bob_infrastructure, bob_domain, "depends_on")
    Rel(runtime, bob_application, "depends_on")
    Rel(runtime, bob_domain, "depends_on")
    Rel(runtime, bob_infrastructure, "depends_on")
```

