---
title: telegram
kind: component
---

# telegram

**Kind:** component

Telegram adapter — aiogram gateway (long-polling, authz gate, native draft streaming, Rich Messages, topic-thread reply pinning), MultiBotGateway (BotRegistry + cross-bot dedup + identity/scope router) and the GuppiHandler gatekeeper.

**Source:** `src/bob/infrastructure/telegram/`

## Public symbols

- `AuthorizerLike`
- `BobMessageFilter`
- `BotIdentity`
- `BotIdentitySignals`
- `BotLike`
- `BotRegistration`
- `BotRegistry`
- `BotScope`
- `BotUserLike`
- `CodingAssistantLike`
- `GoalStoreLike`
- `GuppiHandler`
- `MarkdownSendBot`
- `MarkdownToRichMessage`
- `MessageEntityLike`
- `MessageLike`
- `MessageReactionCountUpdatedLike`
- `MessageReactionUpdatedLike`
- `MultiBotGateway`
- `ProactivityStoreLike`
- `PursuitStoreLike`
- `RichMarkdownSender`
- `RichMessageSerializer`
- `RuleStoreLike`
- `TelegramGateway`
- `UpdateLike`
- `is_reaction_update`

## Relationships

- **part_of**: [bob-infrastructure](../domains/bob-infrastructure.md)
- **depends_on**: [bob-application](../domains/bob-application.md), [proactivity](../features/proactivity.md), [runtime-app](../features/runtime-app.md)
- **Used by**: [bob](../services/bob.md), [coding](../features/coding.md), [runtime](../services/runtime.md), [social](../features/social.md)

## Documentation

- [domains/infrastructure/features/telegram/SPEC.md](/docs/domains/infrastructure/features/telegram/SPEC.md)

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

