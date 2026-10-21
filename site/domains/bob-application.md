---
title: bob-application
kind: domain
---

# bob-application

**Kind:** domain

GUPPI orchestration: AgentRuntime + AsyncEventBus, LLMRouter (tier routing + privacy redaction), use-cases (HandleMessage, RunGenesis, UpdateMoodFromText), resilient heartbeat ticks (retry/backoff), the Authorizer access policy and the capability seam (CapabilityRegistry + ToolLoop + recall_memory). Depends on domain via ports; never imports infrastructure.

**Source:** `src/bob/application/`

## Public symbols

- `call_with_retry`

## Relationships

- **part_of**: [bob](../services/bob.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md)
- **Used by**: [bob-infrastructure](../domains/bob-infrastructure.md), [capabilities](../features/capabilities.md), [runtime](../services/runtime.md), [telegram](../other/telegram.md), [usecases](../features/usecases.md)
- **Parts**: [router](../features/router.md), [runtime-app](../features/runtime-app.md), [usecases](../features/usecases.md)

## Documentation

- [domains/application/README.md](/docs/domains/application/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="bob-application" :depth="1" height="60vh" />
</ClientOnly>

