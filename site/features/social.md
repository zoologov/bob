---
title: social
kind: feature
---

# social

**Kind:** feature

Social module («Bob distinguishes people») — the full vertical capability in one place: `ports.py` + pure domain (interlocutor identity, first-impression, relationship, sulk) + `permission/` value objects, `usecases/` (authorizer/sender+reactor perception, permission flow/execution, first-impression/relationship/sulk sources, run-genesis), and `adapters/` (first-impression/relationship/sulk/allowlist/permission-request/soul stores + privilege-judge). Domain-first slice BOB-062.5.

**Source:** `src/bob/social/`

## Public symbols

- `AllowlistStore`
- `Authorizer`
- `DurableAuthorizer`
- `FirstImpression`
- `FirstImpressionStore`
- `FirstImpressionTracker`
- `GenesisError`
- `GenesisResult`
- `GroupSilentAnnouncer`
- `Interlocutor`
- `InterlocutorKind`
- `KvAllowlistStore`
- `LlmPrivilegeJudge`
- `PermissionDecision`
- `PermissionExecutor`
- `PermissionExecutorLike`
- `PermissionFlow`
- `PermissionNotifier`
- `PermissionRequest`
- `PermissionRequestStoreLike`
- `PermissionState`
- `PersonSulkStore`
- `PrivilegeContext`
- `PrivilegeJudge`
- `PrivilegeJudgeParseError`
- `PrivilegeNeed`
- `PrivilegedFulfiller`
- `ReactorPerception`
- `Relationship`
- `RelationshipDeltas`
- `RelationshipStore`
- `RelationshipTracker`
- `RequesterChannel`
- `RunGenesis`
- `SenderPerception`
- `SocialContext`
- `SoulStore`
- `SqliteFirstImpressionStore`
- `SqlitePermissionRequestStore`
- `SqlitePersonSulkStore`
- `SqliteRelationshipStore`
- `SqliteSulkStore`
- `SulkAnnouncer`
- `SulkConfig`
- `SulkRecoveryStep`
- `SulkState`
- `SulkStore`
- `SulkTracker`
- `Trust`
- `apply_interaction`
- `build_privilege_user_prompt`
- `classify`
- `compromise_bias`
- `detected_endorsement`
- `endorsed_seed`
- `endorsement_seed`
- `filter_surfaceable`
- `impression_note_for`
- `is_authorize`
- `is_deny`
- `is_grant`
- `may_surface`
- `observe_relationship`
- `owner_endorsed_sender`
- `parse_privilege_need`
- `recover`
- `visibility_for_scope`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [personality](../features/personality.md), [router](../features/router.md), [telegram](../other/telegram.md)
- **Used by**: [bob](../services/bob.md), [runtime](../services/runtime.md), [usecases](../features/usecases.md)

## Documentation

- [domains/social/README.md](/docs/domains/social/README.md)

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

