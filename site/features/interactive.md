---
title: interactive
kind: feature
---

# interactive

**Kind:** feature

Interactive module («Боб держит живой терминал») — the live bidirectional `claude` session in the owner's DM: pure domain (mode intent, resume policy + negotiation, argv policy, the mode's voice, the live-session holder), `usecases/` (session manager, teardown, DM intake router, boot-time sweep of orphaned sessions), and `adapters/` (the persistent stream-json runner). Rests on coding's shared session surface; coding never imports it. Split out of `coding` in BOB-087.E.

**Source:** `src/bob/interactive/`

## Public symbols

- `DenialWatch`
- `InteractiveClaudeRunner`
- `InteractiveIntakeRouter`
- `InteractiveManagerLike`
- `InteractiveProcess`
- `InteractiveProcessSpawner`
- `InteractiveRunError`
- `InteractiveSessionManager`
- `LiveSession`
- `OwnerDmNotifierLike`
- `PermissionDenial`
- `PermissionGranted`
- `PermissionNegotiation`
- `PermissionRefused`
- `RecoverInteractiveSessions`
- `ResumeConfirmed`
- `ResumeNegotiation`
- `ResumeRejected`
- `ResumeSupportLike`
- `SessionTeardown`
- `build_interactive_argv`
- `encode_user_message`
- `extract_session_id`
- `interactive_busy`
- `interactive_ended`
- `interactive_ended_persistent`
- `interactive_failed`
- `interactive_opened`
- `interactive_setup_failed`
- `is_confirmation`
- `is_confirmation_fresh`
- `is_interactive_exit`
- `is_rejection`
- `parse_interactive_entry`
- `parse_interactive_resume`
- `parse_interactive_workspace`
- `permission_declined`
- `permission_lifted`
- `permission_question`
- `permission_retry_frame`
- `permission_stuck`
- `permission_unreachable`
- `pipeline_first_frame`
- `resume_cancelled`
- `resume_confirm`
- `resume_failed`
- `resume_nothing`
- `resumed`
- `select_resumable`
- `stopped_persistent`
- `tool_permission_argv`
- `workspace_opened`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [coding](../features/coding.md), [identity](../features/identity.md)
- **Used by**: [runtime](../services/runtime.md)

## Documentation

- [domains/interactive/README.md](/docs/domains/interactive/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="interactive" :depth="1" height="60vh" />
</ClientOnly>

