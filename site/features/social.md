---
title: social
kind: feature
---

# social

**Kind:** feature

Social module («Bob distinguishes people») — the full vertical capability in one place: `ports.py` + pure domain behaviour over the shared-kernel social values (classify an interlocutor, self-gender inference, first-impression, relationship accrual, roster building, sulk dynamics — the values Interlocutor/Gender/Relationship/RosterMember/SulkState live in `kernel`, BOB-113) + `permission/` value objects, `usecases/` (authorizer/sender+reactor perception, permission flow/execution, first-impression/relationship/sulk sources, run-genesis), and `adapters/` (first-impression/relationship/sulk/allowlist/permission-request/soul stores + privilege-judge). Domain-first slice BOB-062.5.

**Source:** `src/bob/social/`

## Public symbols

- `AllowlistStore`
- `Authorizer`
- `DestinationKind`
- `DestinationOutcome`
- `DestinationVerdict`
- `DisclosureConsentContext`
- `DisclosureConsentJudge`
- `DurableAuthorizer`
- `FirstImpression`
- `FirstImpressionReader`
- `FirstImpressionStore`
- `FirstImpressionTracker`
- `GenderMemory`
- `GenderRead`
- `GenesisError`
- `GenesisResult`
- `GroupSilentAnnouncer`
- `InterlocutorResolver`
- `KnownDestination`
- `KvAllowlistStore`
- `LlmDisclosureConsentJudge`
- `LlmPrivilegeJudge`
- `PermissionDecision`
- `PermissionExecutor`
- `PermissionExecutorLike`
- `PermissionFlow`
- `PermissionNotifier`
- `PermissionRequest`
- `PermissionRequestStoreLike`
- `PermissionState`
- `PersonDirectoryLike`
- `PersonHandle`
- `PersonSulkStore`
- `PrivilegeContext`
- `PrivilegeJudge`
- `PrivilegeJudgeParseError`
- `PrivilegeNeed`
- `PrivilegedFulfiller`
- `ReactorPerception`
- `RelationshipDeltas`
- `RelationshipReader`
- `RelationshipStore`
- `RelationshipTracker`
- `RequesterChannel`
- `RosterRecall`
- `RosterRecaller`
- `RunGenesis`
- `SenderPerception`
- `SocialContext`
- `SoulStore`
- `SqliteFirstImpressionStore`
- `SqlitePermissionRequestStore`
- `SqlitePersonSulkStore`
- `SqliteRelationshipStore`
- `SqliteSulkStore`
- `SulkAnnouncer`
- `SulkConfig`
- `SulkReader`
- `SulkRecoveryStep`
- `SulkStore`
- `SulkTracker`
- `apply_interaction`
- `build_disclosure_consent_user_prompt`
- `build_privilege_user_prompt`
- `build_roster`
- `carries_owner_private`
- `classify`
- `compromise_bias`
- `demote_mentions`
- `detect_self_gender`
- `detected_endorsement`
- `endorsed_seed`
- `endorsement_seed`
- `filter_surfaceable`
- `ground_mentions`
- `handles_from`
- `impression_note_for`
- `is_authorize`
- `is_deny`
- `is_grant`
- `is_newcomer`
- `may_surface`
- `member_name`
- `mention_for`
- `observe_relationship`
- `owner_endorsed_sender`
- `owner_permission_notice`
- `parse_disclosure_consent`
- `parse_privilege_need`
- `recover`
- `requester_ack`
- `resolve_destination`
- `transfer_needs_consent`
- `visibility_for_scope`
- `visibility_of`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md), [conversation](../features/conversation.md), [personality](../features/personality.md), [router](../features/router.md), [telegram](../other/telegram.md)
- **Used by**: [capabilities](../features/capabilities.md), [coding](../features/coding.md), [runtime](../services/runtime.md), [usecases](../features/usecases.md)

## Documentation

- [domains/social/README.md](/docs/domains/social/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="social" :depth="1" height="60vh" />
</ClientOnly>

