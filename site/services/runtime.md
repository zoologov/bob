---
title: runtime
kind: service
---

# runtime

**Kind:** service

Composition root (`src/bob/runtime/` package + the thin `app.py` shim) — the only layer allowed to wire all layers + all vertical modules at once: `config.py` loads layered config (incl. `_REPO_ROOT`), `wiring/*` build infrastructure adapters + compose application policy/use-cases per bounded context, `composition.py` (`build_application` + `Application`) subscribes handlers to the EventBus and registers ticks + Telegram polling, `clock.py` provides `SystemClock`, and `main.py` runs Genesis once and starts the process.

**Source:** `src/bob/runtime/`

## Public symbols

- `Application`
- `LlmHealth`
- `RhythmWiring`
- `RosterConfig`
- `SystemClock`
- `build_application`
- `build_batch_room_reader`
- `build_catch_up_reentry`
- `build_disclosure_consent_gate`
- `build_disclosure_guard`
- `build_endorsement_seeder`
- `build_health_policy`
- `build_llm_health`
- `build_outage_episode_writer`
- `build_owner_alert_sink`
- `build_register_resolver`
- `build_rhythm_wiring`
- `build_room_mood_modulator`
- `build_roster_config`
- `build_secondary_recall`
- `build_self_action_recorder`
- `build_send_to_chat`
- `build_staleness_reassessor`
- `build_understudy_stand_down`
- `build_work_journal_recorder`
- `collect_requirements`
- `configured_understudy`
- `health_owner_name`
- `known_destinations`
- `main`
- `report_tool_health`
- `report_understudy`
- `staleness_enabled`

## Relationships

- **part_of**: [bob](../services/bob.md)
- **depends_on**: [bob-application](../domains/bob-application.md), [bob-domain](../domains/bob-domain.md), [bob-infrastructure](../domains/bob-infrastructure.md), [capabilities](../features/capabilities.md), [coding](../features/coding.md), [config](../other/config.md), [conversation](../features/conversation.md), [identity](../features/identity.md), [interactive](../features/interactive.md), [llm](../other/llm.md), [memory](../features/memory.md), [persistence](../other/persistence.md), [personality](../features/personality.md), [presence](../features/presence.md), [proactivity](../features/proactivity.md), [router](../features/router.md), [runtime-app](../features/runtime-app.md), [social](../features/social.md), [telegram](../other/telegram.md), [usecases](../features/usecases.md)

## Documentation

- [services/runtime.md](/docs/services/runtime.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="runtime" :depth="1" height="60vh" />
</ClientOnly>

