---
title: usecases
kind: feature
---

# usecases

**Kind:** feature

Use-cases — HandleMessage, RunGenesis, UpdateMoodFromText, goal/memory/reflection flows orchestrating domain + ports.

**Source:** `src/bob/application/usecases/`

## Public symbols

- `BargeCeiling`
- `BobMessageLookup`
- `CatchUp`
- `CatchUpOutcome`
- `DisclosureConsentGate`
- `DisclosureGuard`
- `EndorsementSeeder`
- `EpisodeWriter`
- `EssentialRunner`
- `FactDeduper`
- `FascinationEvolver`
- `HandleMessage`
- `InnerMonologueTick`
- `InteractiveRouterLike`
- `MemoryConsolidator`
- `MoodDriftTick`
- `NaturalCodingRouter`
- `OutageNotifier`
- `OwnerActivityRecorder`
- `PatternDetectorStep`
- `PerceiveReaction`
- `PermissionFlowLike`
- `PhantomEvolver`
- `PreComposeGate`
- `PrivilegedRequestFulfiller`
- `ReactionMemoryWriter`
- `ReactorResolver`
- `Reappraiser`
- `ReflectTick`
- `ReflectionContext`
- `ReplyDelay`
- `RoomMoodModulator`
- `RuleAnnouncerStep`
- `SelfImprovementReader`
- `SulkRecoverer`
- `TasteProfileWriter`
- `reply_delay_inputs`
- `to_backlog_message`

## Relationships

- **part_of**: [bob-application](../domains/bob-application.md)
- **depends_on**: [bob-application](../domains/bob-application.md), [bob-domain](../domains/bob-domain.md), [capabilities](../features/capabilities.md), [conversation](../features/conversation.md), [memory](../features/memory.md), [personality](../features/personality.md), [presence](../features/presence.md), [proactivity](../features/proactivity.md), [router](../features/router.md), [runtime-app](../features/runtime-app.md), [social](../features/social.md)
- **Used by**: [runtime](../services/runtime.md)

## Documentation

- [domains/application/features/usecases/SPEC.md](/docs/domains/application/features/usecases/SPEC.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="usecases" :depth="1" height="60vh" />
</ClientOnly>

