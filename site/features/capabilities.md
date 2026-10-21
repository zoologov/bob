---
title: capabilities
kind: feature
---

# capabilities

**Kind:** feature

Capabilities module («Bob's tools») — the full vertical GUPPI tool seam in one place: `ports.py` (Capability contract + web/url/diagram/introspection/outbound ports; the LLM tool-calling vocabulary lives in `kernel`, BOB-113) + pure `diagrams`/`introspection` cores (PrivacyGuard, tracker intent/digest, graph form + impact digest, health form + health digest — every dynamic argv slot is validated and every long report is condensed BEFORE it reaches a chat), `usecases/` (CapabilityRegistry + ToolLoop and the skills: recall/search memory, read code/url, web search, render diagram, progress announcer; repo navigation — list_dir / find_file / read_code (BOB-067); read-only dev introspection — recent_commits git history + list_tasks / show_task / task_comments over the beads tracker (BOB-081); and the read-only beadloom trio — draw_architecture (the mermaid source of the graph), architecture_impact («что сломается, если тронуть X») and project_health (status / prime / doctor / sync-check / lint / diff) (BOB-091)), and `adapters/` (aiohttp URL reader behind an SSRF guard, mermaid renderer, beadloom/bd/git introspector over a fixed read-only allowlist — never a shell, Qwen web-search transport). Domain-first slice BOB-062.4.

**Source:** `src/bob/capabilities/`

## Public symbols

- `ArchitectureDiagram`
- `Capability`
- `CapabilityNotAllowedError`
- `CapabilityRegistry`
- `CollectingDiagramSink`
- `DeliveryScope`
- `DeniedPathError`
- `DiagramAttachment`
- `DiagramGateway`
- `DiagramRenderError`
- `DiagramRenderer`
- `DiagramResult`
- `DiagramSender`
- `DiagramSink`
- `DisallowedCommandError`
- `GatewayProgressAnnouncer`
- `GraphForm`
- `HealthForm`
- `HealthRequestError`
- `HttpUrlReader`
- `InterimLineGenerator`
- `IntrospectionError`
- `InvalidGitRefError`
- `MaterialOrigin`
- `MaterialTrailRecall`
- `OutboundMessenger`
- `PrivacyGuard`
- `ProgressAnnouncer`
- `ProjectHealth`
- `QwenWebSearchProvider`
- `RepoIntrospector`
- `SafeCapabilityDispatcher`
- `SsrfBlockedError`
- `SubprocessMmdcRenderer`
- `SubprocessRepoIntrospector`
- `ToolLoop`
- `ToolRequirement`
- `ToolVerdict`
- `TrackerPlan`
- `TurnMaterial`
- `UnknownCapabilityError`
- `UnknownCheckError`
- `UrlReadError`
- `UrlReader`
- `WebPage`
- `WebSearchProvider`
- `WebSearchResult`
- `WebSource`
- `armed_delivery_scope`
- `armed_turn_material`
- `assess_tools`
- `build_url_reader`
- `clamp_commit_count`
- `clamp_graph_depth`
- `commits_mentioning`
- `current_delivery_scope`
- `current_turn_material`
- `describe_unavailable`
- `diagram_carries_nodes`
- `digest_health`
- `digest_impact`
- `digest_search_results`
- `drawn_reply`
- `extract_mermaid_blocks`
- `feature_doc_dir`
- `find_bead_key`
- `is_bead_id`
- `is_git_ref`
- `is_graph_ref`
- `make_architecture_impact_capability`
- `make_code_rationale_capability`
- `make_draw_architecture_capability`
- `make_find_file_capability`
- `make_inspect_architecture_capability`
- `make_list_dir_capability`
- `make_list_tasks_capability`
- `make_list_work_capability`
- `make_project_health_capability`
- `make_read_code_capability`
- `make_read_url_capability`
- `make_recall_memory_capability`
- `make_recent_commits_capability`
- `make_render_diagram_capability`
- `make_search_memory_capability`
- `make_send_to_chat_capability`
- `make_show_task_capability`
- `make_task_comments_capability`
- `make_web_search_capability`
- `normalize_check`
- `normalize_mermaid`
- `normalize_status`
- `not_found_reply`
- `parse_bead_refs`
- `plan_graph_form`
- `plan_health_form`
- `plan_tracker_query`
- `refused_reply`
- `resolve_tool`
- `sanitize_search_term`
- `strip_mermaid_blocks`
- `unavailable`
- `validate_bead_id`
- `validate_git_ref`
- `validate_graph_ref`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [bob-application](../domains/bob-application.md), [bob-domain](../domains/bob-domain.md), [memory](../features/memory.md), [router](../features/router.md), [social](../features/social.md)
- **Used by**: [coding](../features/coding.md), [llm](../other/llm.md), [runtime](../services/runtime.md), [usecases](../features/usecases.md)

## Documentation

- [domains/capabilities/README.md](/docs/domains/capabilities/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="capabilities" :depth="1" height="60vh" />
</ClientOnly>

