---
title: runtime-app
kind: feature
---

# runtime-app

**Kind:** feature

Application runtime — AgentRuntime, AsyncEventBus, and resilient heartbeat ticks (retry/backoff); the intake events it carries live in the shared kernel. Distinct from the `runtime` composition root.

**Source:** `src/bob/application/runtime/`

## Public symbols

- `AgentRuntime`
- `AmbientBatchReader`
- `AsyncEventBus`
- `CatchUpReentry`
- `CatchUpSelection`
- `ChatDispatcher`
- `ChatInbox`
- `DelayedTurn`
- `RetryPolicy`
- `RoomStreamReader`
- `RuntimeState`
- `ShareOfVoiceGate`
- `StalenessReassessor`
- `TurnScope`
- `batch_grew`
- `derive_turn_seed`
- `is_transient`
- `make_focus_predicate`
- `message_is_focused`
- `new_turn_scope`
- `periodic`
- `retry_with_backoff`
- `should_debounce`

## Relationships

- **part_of**: [bob-application](../domains/bob-application.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md), [conversation](../features/conversation.md), [presence](../features/presence.md)
- **Used by**: [memory](../features/memory.md), [runtime](../services/runtime.md), [usecases](../features/usecases.md)

## Documentation

- [domains/application/features/runtime-app/SPEC.md](/docs/domains/application/features/runtime-app/SPEC.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="runtime-app" :depth="1" height="60vh" />
</ClientOnly>

