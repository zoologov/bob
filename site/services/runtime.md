---
title: runtime
kind: service
---

# runtime

**Kind:** service

Composition root (`src/bob/runtime/` package + the thin `app.py` shim) — the only layer allowed to wire all layers + all vertical modules at once: `config.py` loads layered config (incl. `_REPO_ROOT`), `wiring/*` build infrastructure adapters + compose application policy/use-cases per bounded context, `composition.py` (`build_application` + `Application`) subscribes handlers to the EventBus and registers ticks + Telegram polling, `clock.py` provides `SystemClock`, and `main.py` runs Genesis once and starts the process.

**Source:** `src/bob/runtime/`

## Public symbols

- `Application`
- `RhythmWiring`
- `SystemClock`
- `build_application`
- `build_batch_room_reader`
- `build_catch_up_reentry`
- `build_disclosure_guard`
- `build_endorsement_seeder`
- `build_rhythm_wiring`
- `build_room_mood_modulator`
- `build_staleness_reassessor`
- `main`
- `staleness_enabled`

## Relationships

- **part_of**: [bob](../services/bob.md)
- **depends_on**: [bob-application](../domains/bob-application.md), [bob-domain](../domains/bob-domain.md), [bob-infrastructure](../domains/bob-infrastructure.md), [capabilities](../features/capabilities.md), [coding](../features/coding.md), [config](../other/config.md), [conversation](../features/conversation.md), [llm](../other/llm.md), [memory](../features/memory.md), [persistence](../other/persistence.md), [personality](../features/personality.md), [presence](../features/presence.md), [proactivity](../features/proactivity.md), [router](../features/router.md), [runtime-app](../features/runtime-app.md), [social](../features/social.md), [telegram](../other/telegram.md), [usecases](../features/usecases.md)
- **Used by**: [bob](../services/bob.md)

## Documentation

- [services/runtime.md](/docs/services/runtime.md)

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

