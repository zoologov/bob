---
title: capabilities
kind: feature
---

# capabilities

**Kind:** feature

Capabilities module («Bob's tools») — the full vertical GUPPI tool seam in one place: `ports.py` (Capability contract + tool/web/diagram/introspection ports) + pure `diagrams`/`introspection` value objects, `usecases/` (CapabilityRegistry + ToolLoop and the skills: recall/search memory, read code/url, web search, render diagram, inspect architecture, progress announcer), and `adapters/` (aiohttp URL reader behind an SSRF guard, mermaid renderer, beadloom/git introspector, Qwen web-search transport). Domain-first slice BOB-062.4.

**Source:** `src/bob/capabilities/`

## Public symbols

- `Capability`
- `CapabilityNotAllowedError`
- `CapabilityRegistry`
- `CollectingDiagramSink`
- `DeniedPathError`
- `DiagramGateway`
- `DiagramRenderError`
- `DiagramRenderer`
- `DiagramResult`
- `DiagramSender`
- `DiagramSink`
- `DisallowedCommandError`
- `GatewayProgressAnnouncer`
- `HttpUrlReader`
- `InterimLineGenerator`
- `IntrospectionError`
- `PrivacyGuard`
- `ProgressAnnouncer`
- `QwenWebSearchProvider`
- `RepoIntrospector`
- `SafeCapabilityDispatcher`
- `SsrfBlockedError`
- `SubprocessMmdcRenderer`
- `SubprocessRepoIntrospector`
- `ToolCall`
- `ToolCallResult`
- `ToolCallingProvider`
- `ToolLoop`
- `UnknownCapabilityError`
- `UrlReadError`
- `UrlReader`
- `WebPage`
- `WebSearchProvider`
- `WebSearchResult`
- `WebSource`
- `build_url_reader`
- `commits_mentioning`
- `extract_mermaid_blocks`
- `feature_doc_dir`
- `make_code_rationale_capability`
- `make_find_file_capability`
- `make_inspect_architecture_capability`
- `make_list_dir_capability`
- `make_list_work_capability`
- `make_read_code_capability`
- `make_read_url_capability`
- `make_recall_memory_capability`
- `make_render_diagram_capability`
- `make_search_memory_capability`
- `make_web_search_capability`
- `normalize_mermaid`
- `parse_bead_refs`
- `strip_mermaid_blocks`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [bob-application](../domains/bob-application.md)
- **Used by**: [llm](../other/llm.md), [runtime](../services/runtime.md), [usecases](../features/usecases.md)

## Documentation

- [domains/capabilities/README.md](/docs/domains/capabilities/README.md)

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

