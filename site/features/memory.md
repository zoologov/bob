---
title: memory
kind: feature
---

# memory

**Kind:** feature

Memory module («Bob remembers») — the full vertical capability in one place: `ports.py` + pure `entities`, `usecases/` (extract facts, consolidate, dedup), and `adapters/` (FTS5/hybrid recall + local Ollama embedder/reranker). Domain-first slice BOB-062.2.

**Source:** `src/bob/memory/`

## Public symbols

- `ConsolidateMemory`
- `ConsolidationStore`
- `DedupFacts`
- `DedupStore`
- `Embedder`
- `EpisodicEvent`
- `ExtractFacts`
- `FactWriter`
- `Fts5MemoryRecall`
- `HybridMemoryRecall`
- `MemoryRecall`
- `MemoryRepo`
- `MemoryVectorStore`
- `OllamaEmbedder`
- `OllamaReranker`
- `Reranker`
- `SemanticFact`
- `SqliteMemoryRepo`
- `build_embedder`
- `build_reranker`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [persistence](../other/persistence.md), [personality](../features/personality.md), [router](../features/router.md), [runtime-app](../features/runtime-app.md)
- **Used by**: [proactivity](../features/proactivity.md), [runtime](../services/runtime.md), [usecases](../features/usecases.md)

## Documentation

- [domains/memory/README.md](/docs/domains/memory/README.md)

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

