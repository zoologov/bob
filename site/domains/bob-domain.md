---
title: bob-domain
kind: domain
---

# bob-domain

**Kind:** domain

Umbrella of the seven module-vertical bounded contexts (personality, conversation, memory, proactivity, coding, capabilities, social) plus the shared `kernel` (infra-neutral cross-module contracts — the domain LAYER proper). Each vertical spans domain+usecases+adapters inside its own boundary; the kernel is pure logic + Protocol definitions: no I/O, no LLM, no transport.

**Source:** `src/bob/kernel/`

## Public symbols

- `BobMessageReaction`
- `BobUserIdSource`
- `Clock`
- `DomainEvent`
- `EpisodeReader`
- `EventBus`
- `Gender`
- `HealthObserver`
- `HealthPolicy`
- `HealthReader`
- `HealthState`
- `HealthView`
- `Interlocutor`
- `InterlocutorKind`
- `LLMProvider`
- `MemoryRecall`
- `MessageReceived`
- `OwnerAlertSink`
- `ProviderHealth`
- `Relationship`
- `ReplyGateway`
- `RosterMember`
- `RuleModulators`
- `SelfReportingProvider`
- `Speaker`
- `SulkState`
- `ToolCall`
- `ToolCallResult`
- `ToolCallingProvider`
- `Transition`
- `Trust`
- `UnderstudyBackedProvider`
- `duration`
- `failure_now`
- `failure_report`
- `failure_then`
- `in_local_zone`
- `is_owner_private`
- `next_backoff`
- `next_probe_interval`
- `on_failure`
- `on_success`
- `outage_duration`
- `outage_state`
- `period`
- `plural`
- `probe_due`
- `provider_speaker`
- `strictest_visibility`
- `under_root`
- `utc_offset_label`

## Relationships

- **part_of**: [bob](../services/bob.md)
- **Used by**: [bob-application](../domains/bob-application.md), [bob-infrastructure](../domains/bob-infrastructure.md), [capabilities](../features/capabilities.md), [coding](../features/coding.md), [conversation](../features/conversation.md), [identity](../features/identity.md), [llm](../other/llm.md), [memory](../features/memory.md), [personality](../features/personality.md), [proactivity](../features/proactivity.md), [router](../features/router.md), [runtime](../services/runtime.md), [runtime-app](../features/runtime-app.md), [social](../features/social.md), [telegram](../other/telegram.md), [usecases](../features/usecases.md)
- **Parts**: [capabilities](../features/capabilities.md), [coding](../features/coding.md), [conversation](../features/conversation.md), [identity](../features/identity.md), [interactive](../features/interactive.md), [kernel](../features/kernel.md), [memory](../features/memory.md), [personality](../features/personality.md), [presence](../features/presence.md), [proactivity](../features/proactivity.md), [social](../features/social.md)

## Documentation

- [domains/domain/README.md](/docs/domains/domain/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="bob-domain" :depth="1" height="60vh" />
</ClientOnly>

