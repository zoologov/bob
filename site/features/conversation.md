---
title: conversation
kind: feature
---

# conversation

**Kind:** feature

Conversation module («how a turn is conducted») — the full turn-conduct vertical in one place: `ports.py` (conversation-floor store, closer log, ZoneClassifier) + pure domain (addressivity, conversation + floor continuity, brevity, engagement, zone classifier, interim line, response choice, response/volatility judgments), `usecases/` (decide_response), and `adapters/` (Tier-0 response/volatility/interim judges + SQLite conversation-floor & closer-log stores). Depends on personality one-directionally. Domain-first slice BOB-062.6a.

**Source:** `src/bob/conversation/`

## Public symbols

- `Addressivity`
- `AddressivityPerceiver`
- `AddressivityThresholds`
- `AnswerDemand`
- `AntiRepeatGuard`
- `BatchAmbientMessage`
- `BatchRoomReader`
- `BatchRoomReading`
- `BatchRoomReadingContext`
- `BrevityThresholds`
- `CloserLog`
- `ConversationFloor`
- `ConversationFloorStore`
- `ConversationalFatigue`
- `DecideResponse`
- `EngagementModel`
- `EngagementThresholds`
- `FatigueRates`
- `FloorConfig`
- `FloorHolder`
- `FloorManager`
- `FloorResolution`
- `LlmBatchRoomReader`
- `LlmInterimLineGenerator`
- `LlmResponseJudge`
- `LlmRoomReader`
- `LlmVolatilityJudge`
- `OutgoingTarget`
- `ReadTheRoom`
- `RecallAssembler`
- `ReflectiveIntent`
- `ReflectiveVerdict`
- `RepeatThresholds`
- `ResponseChoice`
- `ResponseContext`
- `ResponseIntent`
- `ResponseJudge`
- `ResponseJudgeParseError`
- `ResponseOutcome`
- `RoomMood`
- `RoomReader`
- `RoomReading`
- `RoomReadingContext`
- `RoomReadingParseError`
- `SqliteCloserLog`
- `SqliteConversationFloorStore`
- `TasteZoneClassifier`
- `TurnGate`
- `VerdictKind`
- `VerifyInterimAnnouncer`
- `VerifyStep`
- `VolatilityContext`
- `VolatilityJudge`
- `VolatilityJudgeParseError`
- `VolatilityVerdict`
- `ZoneClassifier`
- `advance_floor`
- `appetite_of`
- `build_batch_room_prompt`
- `build_interim_line_user_prompt`
- `build_judgment_user_prompt`
- `build_room_prompt`
- `build_volatility_user_prompt`
- `clamp_reply`
- `classify_addressivity`
- `classify_answer_demand`
- `clean_interim_line`
- `closer_text`
- `decide_batch`
- `decide_engagement`
- `decide_from_reading`
- `decide_response`
- `decide_verbosity`
- `engagement_mood_lift`
- `idle_floor`
- `is_bob_repeat`
- `is_floor_participant`
- `is_phrase_tic`
- `is_recurring_closer_tic`
- `is_same_closer_motif`
- `is_user_repeat`
- `others_present`
- `parse_batch_reading`
- `parse_response_choice`
- `parse_room_reading`
- `parse_volatility_verdict`
- `recalled_bob_replies`
- `recalled_bob_reply`
- `recalled_excluding_reflections`
- `recalled_without_copied_exemplars`
- `recurring_closer`
- `resolve_addressivity`
- `resolve_outgoing_target`
- `strip_recurring_closer`
- `topic_interest`
- `validate_reaction_emoji`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [personality](../features/personality.md), [router](../features/router.md)
- **Used by**: [proactivity](../features/proactivity.md), [runtime](../services/runtime.md), [runtime-app](../features/runtime-app.md), [usecases](../features/usecases.md)

## Documentation

- [domains/conversation/README.md](/docs/domains/conversation/README.md)

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

