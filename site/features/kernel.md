---
title: kernel
kind: feature
---

# kernel

**Kind:** feature

Shared kernel — the infra-neutral contracts every vertical module rests on: the runtime seams (Clock, EventBus, EventHandler, DomainEvent, LLMProvider), the shared value objects (LLMMessage, JsonValue), the intake events (MessageReceived, BobMessageReaction), the memory/reply ports (EpisodeReader, MemoryRecall, Recalled, ReplyGateway, BobUserIdSource), the LLM tool-calling vocabulary (ToolDefinition, ToolCall, ToolCallResult, ToolCallingProvider, ToolLoopMessage), the self-improvement RuleModulators, and the social vocabulary — who talks to Bob and how he stands with them (Interlocutor, InterlocutorKind, Trust, Gender, Relationship, RosterMember, SulkState) — whose behaviour stays in `social` (BOB-113). Pure Protocol/type/value definitions; no I/O. Every module may import from here; the kernel imports from no module.

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

- **part_of**: [bob-domain](../domains/bob-domain.md)

## Documentation

- [domains/domain/features/kernel/SPEC.md](/docs/domains/domain/features/kernel/SPEC.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="kernel" :depth="1" height="60vh" />
</ClientOnly>

