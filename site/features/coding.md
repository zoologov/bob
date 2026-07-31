---
title: coding
kind: feature
---

# coding

**Kind:** feature

Coding module («Bob writes code») — the full vertical capability in one place: `ports.py` + pure domain logic, `usecases/` orchestration, and `adapters/` (Claude Code CLI, git worktree, gh PR, session store, indicator). Domain-first slice BOB-062.1.

**Source:** `src/bob/coding/`

## Public symbols

- `ClassifyCodingIntent`
- `ClaudeCodeRunner`
- `ClaudeRunError`
- `CodingAssistant`
- `CodingContext`
- `CodingIntentClassifierLike`
- `CodingIntentRouter`
- `CodingOutcome`
- `CodingSession`
- `CodingSessionState`
- `CodingSessionStore`
- `CommandError`
- `CommandRunner`
- `EditableStatusBot`
- `ExecRunner`
- `GatedCoder`
- `GhPullRequestOpener`
- `GitWorktree`
- `OwnerCheck`
- `OwnerNotifier`
- `PullRequestError`
- `PullRequestOpener`
- `SqliteCodingSessionStore`
- `StatusPanel`
- `StreamLineRunner`
- `SubprocessClaudeRunner`
- `TypingActionBot`
- `TypingKeepalive`
- `Worktree`
- `WorktreeError`
- `accepted`
- `busy`
- `can_approve_plan`
- `can_start`
- `can_stop`
- `can_transition`
- `cannot_approve`
- `failed`
- `is_approval`
- `is_safe_branch`
- `is_stop`
- `is_terminal`
- `make_coding_context`
- `narrate`
- `no_changes`
- `no_session`
- `panel_executing`
- `panel_failed`
- `panel_plan_ready`
- `panel_planning`
- `panel_pr`
- `panel_stopped`
- `plan`
- `pr`
- `status_idle`
- `status_line`
- `stopped`
- `worktree_branch`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [router](../features/router.md), [telegram](../other/telegram.md)
- **Used by**: [bob](../services/bob.md), [runtime](../services/runtime.md)

## Documentation

- [domains/coding/README.md](/docs/domains/coding/README.md)

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

