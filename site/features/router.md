---
title: router
kind: feature
---

# router

**Kind:** feature

LLMRouter — Tier 0/1 model routing with privacy redaction before any model call.

**Source:** `src/bob/application/router/`

## Public symbols

- `GenerationDoor`
- `LLMRequest`
- `LLMRouter`
- `OutageVoice`
- `TaskType`
- `VoiceCanon`
- `door_for`
- `fold_voice_canon`
- `select_reply_tier`
- `should_fall_back`
- `who_may_answer_for_bob`

## Relationships

- **part_of**: [bob-application](../domains/bob-application.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md)
- **Used by**: [capabilities](../features/capabilities.md), [coding](../features/coding.md), [conversation](../features/conversation.md), [llm](../other/llm.md), [memory](../features/memory.md), [personality](../features/personality.md), [presence](../features/presence.md), [proactivity](../features/proactivity.md), [runtime](../services/runtime.md), [social](../features/social.md), [usecases](../features/usecases.md)

## Documentation

- [domains/application/features/router/SPEC.md](/docs/domains/application/features/router/SPEC.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="router" :depth="1" height="60vh" />
</ClientOnly>

