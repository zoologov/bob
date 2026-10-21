---
title: coding
kind: feature
---

# coding

**Kind:** feature

Coding module («Bob writes code») — the GATED vertical (plan → approve → PR) plus the shared coding-session surface: `ports.py` + pure domain logic (state/naming/sandbox+push policy/stream-json), `usecases/` orchestration, and `adapters/` (Claude Code CLI, git worktree, gh PR, session store, indicator). Domain-first slice BOB-062.1; the live terminal split out into `interactive` in BOB-087.E.

**Source:** `src/bob/coding/`

## Public symbols

- `ClassifyCodingIntent`
- `ClaudeCodeRunner`
- `ClaudeRunError`
- `CloneError`
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
- `DistillingWorkJournalRecorder`
- `EditableStatusBot`
- `ExecRunner`
- `ForkCompareLink`
- `GatedCoder`
- `GhPullRequestOpener`
- `GitClone`
- `GitWorktree`
- `InteractiveRunner`
- `LiveRunStreamer`
- `MessageKind`
- `NoOpWorkJournalRecorder`
- `OwnerCheck`
- `OwnerNotifier`
- `PersistentWorkspace`
- `PullRequestError`
- `PullRequestOpener`
- `ResumableSessionLookup`
- `SessionKeyFacts`
- `Speaker`
- `SqliteCodingSessionStore`
- `StatusPanel`
- `StreamLineRunner`
- `SubprocessClaudeRunner`
- `Tier0WorkJournalDistiller`
- `TypingActionBot`
- `TypingKeepalive`
- `WorkEpisodeStore`
- `WorkFactsAccumulator`
- `WorkJournalDistiller`
- `WorkJournalRecorder`
- `WorkOutcome`
- `WorkspaceVerdict`
- `Worktree`
- `WorktreeError`
- `accepted`
- `allowed_modes`
- `build_work_journal_messages`
- `busy`
- `can_approve_plan`
- `can_start`
- `can_stop`
- `can_transition`
- `cannot_approve`
- `channel_for`
- `checkout_argv`
- `chunk_for_telegram`
- `clone_argv`
- `commit_and_push_branch`
- `compare_url`
- `dev_pointer`
- `extra_dir_argv`
- `failed`
- `fetch_argv`
- `guarded_spawn_env`
- `hardened_git_argv`
- `identity_argv`
- `identity_pins`
- `is_allowed_mode`
- `is_approval`
- `is_credential_free_url`
- `is_mechanical`
- `is_safe_argv_value`
- `is_safe_branch`
- `is_stop`
- `is_strict_child`
- `is_terminal`
- `make_coding_context`
- `narrate`
- `narration_capped`
- `no_changes`
- `no_session`
- `notifier_for`
- `origin_argv`
- `panel_executing`
- `panel_failed`
- `panel_plan_ready`
- `panel_planning`
- `panel_pr`
- `panel_ready_for_pr`
- `panel_stopped`
- `parse_event`
- `parse_work_episodes`
- `plan`
- `pr`
- `ready_for_pr`
- `render_stream_event`
- `repo_slug`
- `speaker_for`
- `status_idle`
- `status_line`
- `stopped`
- `tracker_argv`
- `unsafe_local_config`
- `workspace_branch`
- `workspace_verdict`
- `worktree_branch`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md), [capabilities](../features/capabilities.md), [identity](../features/identity.md), [memory](../features/memory.md), [router](../features/router.md), [social](../features/social.md), [telegram](../other/telegram.md)
- **Used by**: [interactive](../features/interactive.md), [runtime](../services/runtime.md)

## Documentation

- [domains/coding/README.md](/docs/domains/coding/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="coding" :depth="1" height="60vh" />
</ClientOnly>

