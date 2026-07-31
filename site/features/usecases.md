---
title: usecases
kind: feature
---

# usecases

**Kind:** feature

Use-cases — HandleMessage, RunGenesis, UpdateMoodFromText, goal/memory/reflection flows orchestrating domain + ports.

**Source:** `src/bob/application/usecases/`

## Public symbols

- `BargeCeiling`
- `BobMessageLookup`
- `BobUserIdSource`
- `CatchUp`
- `CatchUpOutcome`
- `CurrentFascinationReader`
- `DisclosureGuard`
- `EndorsementSeeder`
- `EngagementState`
- `EpisodeReader`
- `EpisodeWriter`
- `EssentialRunner`
- `FactDeduper`
- `FascinationEvolver`
- `FirstImpressionReader`
- `HandleMessage`
- `InnerMonologueTick`
- `InterlocutorResolver`
- `MemoryConsolidator`
- `MoodDriftTick`
- `NaturalCodingRouter`
- `OutageNotifier`
- `OwnerActivityRecorder`
- `PatternDetectorStep`
- `PerceiveReaction`
- `PermissionFlowLike`
- `PersonalityState`
- `PhantomEvolver`
- `PreComposeGate`
- `PrivilegedRequestFulfiller`
- `ReactionMemoryWriter`
- `ReactorResolver`
- `Reappraiser`
- `ReflectTick`
- `ReflectionContext`
- `RelationshipReader`
- `ReplyDelay`
- `ReplyGateway`
- `RoomMoodModulator`
- `RuleAnnouncerStep`
- `SelfImprovementReader`
- `SulkReader`
- `SulkRecoverer`
- `TasteProfileWriter`
- `reply_delay_inputs`
- `to_backlog_message`

## Relationships

- **part_of**: [bob-application](../domains/bob-application.md)
- **depends_on**: [bob-application](../domains/bob-application.md), [capabilities](../features/capabilities.md), [conversation](../features/conversation.md), [memory](../features/memory.md), [personality](../features/personality.md), [presence](../features/presence.md), [proactivity](../features/proactivity.md), [router](../features/router.md), [social](../features/social.md)
- **Used by**: [runtime](../services/runtime.md)

## Documentation

- [domains/application/features/usecases/SPEC.md](/docs/domains/application/features/usecases/SPEC.md)

## Diagram

```mermaid
C4Container
    System_Boundary(bob_boundary, "Bob") {
        Container(bob_application, "Bob Application", "", "GUPPI orchestration: AgentRuntime + AsyncEventBus, LLMRouter (tier routing + privacy redaction), use-cases (HandleMessage, RunGenesis, UpdateMoodFromText), resilient heartbeat ticks (retry/backoff), the Authorizer access policy and the capability seam (CapabilityRegistry + ToolLoop + recall_memory). Depends on domain via ports; never imports infrastructure.")
        Container(bob_domain, "Bob Domain", "", "Domain layer umbrella: the seven module-vertical bounded contexts (personality, conversation, memory, proactivity, coding, capabilities, social) plus the shared `kernel` (infra-neutral cross-module contracts). Pure logic + Protocol definitions; no I/O, no LLM, no transport.")
        Container(bob_infrastructure, "Bob Infrastructure", "", "Port adapters: aiogram Telegram gateway (long-polling + authz gate, native draft streaming, Rich Messages, markdown<->RichMessage, topic-thread reply pinning), MultiBotGateway (BotRegistry + cross-bot dedup + central identity/scope router) and the GuppiHandler gatekeeper (visible reject + owner commands), OpenAI-compatible LLM provider (Tier 0/1 + tool-calling), SQLite+FTS5 persistence, KvAllowlistStore and SoulStore, two-bot layered config loader.")
        Container(runtime, "Runtime", "", "Composition root (`src/bob/runtime/` package + the thin `app.py` shim) — the only layer allowed to wire all layers + all vertical modules at once: `config.py` loads layered config (incl. `_REPO_ROOT`), `wiring/*` build infrastructure adapters + compose application policy/use-cases per bounded context, `composition.py` (`build_application` + `Application`) subscribes handlers to the EventBus and registers ticks + Telegram polling, `clock.py` provides `SystemClock`, and `main.py` runs Genesis once and starts the process.")
    }
    Rel(bob_application, bob_domain, "depends_on")
    Rel(bob_infrastructure, bob_application, "depends_on")
    Rel(bob_infrastructure, bob_domain, "depends_on")
    Rel(runtime, bob_application, "depends_on")
    Rel(runtime, bob_domain, "depends_on")
    Rel(runtime, bob_infrastructure, "depends_on")
```

