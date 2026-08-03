# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root capability wiring — the registry GUPPI advertises + diagram/introspect.

Builds the :class:`CapabilityRegistry` (memory recall/search always; self-introspection,
diagram render, web search and read-url behind their flags), the LOCAL
:class:`SubprocessMmdcRenderer` and the :class:`SubprocessRepoIntrospector` (guarded by the
pure :class:`PrivacyGuard`). Returns the shared :class:`CollectingDiagramSink` + renderer so
the composition root wires the SAME instances into HandleMessage. Part of the ``bob.runtime``
composition root (BOB-062.7a).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.adapters.diagrams import SubprocessMmdcRenderer
from bob.capabilities.adapters.introspection.subprocess_introspector import (
    SubprocessRepoIntrospector,
)
from bob.capabilities.adapters.web import build_url_reader
from bob.capabilities.introspection.privacy_guard import PrivacyGuard
from bob.capabilities.usecases import (
    CapabilityRegistry,
    CollectingDiagramSink,
    make_code_rationale_capability,
    make_find_file_capability,
    make_inspect_architecture_capability,
    make_list_dir_capability,
    make_list_tasks_capability,
    make_list_work_capability,
    make_read_code_capability,
    make_read_url_capability,
    make_recall_memory_capability,
    make_recent_commits_capability,
    make_render_diagram_capability,
    make_search_memory_capability,
    make_show_task_capability,
    make_task_comments_capability,
    make_web_search_capability,
)
from bob.infrastructure.llm import build_web_search_provider
from bob.runtime.config import (
    _DEFAULT_DIAGRAM_BACKGROUND,
    _DEFAULT_DIAGRAM_SCALE,
    _DEFAULT_DIAGRAM_TIMEOUT_S,
    _DEFAULT_INTROSPECTION_MAX_OUTPUT_CHARS,
    _DEFAULT_INTROSPECTION_READ_MAX_LINES,
    _REPO_ROOT,
    _flag,
    _int,
    _section,
    _str,
)
from bob.runtime.wiring.parameters import (
    _build_dev_tools_enabled,
    _build_introspection_enabled,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.memory.ports import MemoryRecall


def _build_registry(
    config: Mapping[str, object], *, recall: MemoryRecall
) -> tuple[CapabilityRegistry, CollectingDiagramSink, SubprocessMmdcRenderer | None]:
    """Build the capability registry GUPPI advertises and dispatches + the diagram sink.

    Always registers the two memory capabilities over the injected
    :class:`~bob.memory.ports.MemoryRecall` — the live hybrid recall, or (BOB-087.C8, when
    ``memory.register_recall`` is on) the CASUAL-floor port that mutes Bob's ``work``
    recollections on this secondary door: ``recall_memory`` (the thin auto-recall
    wrapper) and ``search_memory`` (BOB-011 — the agentic skill Bob chooses to
    invoke through the tool-loop). When ``introspection.enabled`` (BOB-017 Phase A,
    default on) the read-only self-introspection skills
    (``inspect_architecture`` / ``read_code`` / ``list_dir`` / ``find_file`` /
    ``list_work`` / ``code_rationale`` — the last linking code↔decisions per BOB-038,
    ``list_dir`` + ``find_file`` letting Bob navigate the WHOLE repo per BOB-067) are
    ALSO registered, over a :class:`SubprocessRepoIntrospector` guarded by the pure
    :class:`PrivacyGuard` — so Bob can answer about his own world. When
    ``diagrams.enabled`` (BOB-035, default on — safe + local) the ``render_diagram``
    skill is registered over a LOCAL :class:`SubprocessMmdcRenderer`, sharing the
    returned :class:`CollectingDiagramSink` with the use-case so a rendered PNG flows
    to the reply path's photo send. They are conversation-only (NOT added to
    ``goals.safe_capabilities``). Disabled → the registry holds exactly the memory
    capabilities, behaviour as before. New skills register here without touching
    consumers. The shared sink is returned so the composition root wires the SAME
    instance into :class:`HandleMessage`; the diagram renderer is returned too so the
    SAME renderer also backs the inline-mermaid auto-render (BOB-037 A), or ``None``
    when diagrams are disabled.
    """
    registry = CapabilityRegistry()
    diagram_sink = CollectingDiagramSink()
    registry.register(make_recall_memory_capability(recall))
    registry.register(make_search_memory_capability(recall))
    if _build_introspection_enabled(config):
        introspector = _build_introspector(config)
        read_max_lines = _int(
            _section(config, "introspection"),
            "read_max_lines",
            _DEFAULT_INTROSPECTION_READ_MAX_LINES,
        )
        registry.register(make_inspect_architecture_capability(introspector))
        registry.register(make_read_code_capability(introspector, read_max_lines=read_max_lines))
        registry.register(make_list_dir_capability(introspector))
        registry.register(make_find_file_capability(introspector))
        registry.register(make_list_work_capability(introspector))
        registry.register(make_code_rationale_capability(introspector))
        # BOB-081: the read-only dev-introspection tools (git history + tracker
        # read) ride the SAME introspector but behind a SUB-flag, default OFF — the
        # git-history + tracker read tools ship as one gated piece. ``list_tasks``
        # (by-status view) coexists with ``list_work`` (free-text query / ready
        # queue): distinct entry points, not a duplicate.
        if _build_dev_tools_enabled(config):
            registry.register(make_recent_commits_capability(introspector))
            registry.register(make_list_tasks_capability(introspector))
            registry.register(make_show_task_capability(introspector))
            registry.register(make_task_comments_capability(introspector))
    diagram_renderer: SubprocessMmdcRenderer | None = None
    if _flag(_section(config, "diagrams"), "enabled"):
        diagram_renderer = _build_diagram_renderer(config)
        registry.register(
            make_render_diagram_capability(diagram_renderer, diagram_sink)
        )
    # Web search (BOB-053): registered ONLY when ``search.enabled`` — the Qwen-native
    # provider stays behind an explicit flag. Privilege is by sender (authz/BOB-052):
    # the tool-loop only runs for an authorised sender, so no extra gate is needed.
    if _flag(_section(config, "search"), "enabled"):
        registry.register(make_web_search_capability(build_web_search_provider(config)))
    # Read URL (BOB-054): the twin of web_search — registered ONLY when
    # ``read_url.enabled`` so the SSRF-guarded page reader stays behind an explicit flag.
    # Privilege is by sender (authz/BOB-052): the tool-loop only runs for an authorised
    # sender, so no extra gate is needed.
    if _flag(_section(config, "read_url"), "enabled"):
        registry.register(make_read_url_capability(build_url_reader(config)))
    return registry, diagram_sink, diagram_renderer


def _build_diagram_renderer(config: Mapping[str, object]) -> SubprocessMmdcRenderer:
    """Construct the LOCAL :class:`SubprocessMmdcRenderer` for BOB-035.

    Renders Mermaid to a PNG by running the local mermaid-cli (``mmdc``) via
    ``create_subprocess_exec`` (never a shell) — no network, the diagram source never
    leaves the machine. The binary name + per-render timeout are config-tunable via
    ``diagrams.{mmdc_bin, timeout}``; the BOB-037 high-quality flags — the
    deviceScaleFactor (``diagrams.scale``) and page background (``diagrams.background``,
    ``white`` for readability on a dark theme) — keep dense diagrams legible.
    """
    section = _section(config, "diagrams")
    return SubprocessMmdcRenderer(
        mmdc_bin=_str(section, "mmdc_bin", "mmdc"),
        timeout=float(_int(section, "timeout", _DEFAULT_DIAGRAM_TIMEOUT_S)),
        scale=_int(section, "scale", _DEFAULT_DIAGRAM_SCALE),
        background=_str(section, "background", _DEFAULT_DIAGRAM_BACKGROUND),
    )


def _build_introspector(config: Mapping[str, object]) -> SubprocessRepoIntrospector:
    """Construct the read-only :class:`SubprocessRepoIntrospector` for BOB-017.

    The pure :class:`PrivacyGuard` (rooted at the repo) enforces the DENY-invariant
    BEFORE any file read; the subprocess adapter runs ``beadloom`` / ``bd`` / ``git``
    against a FIXED read-only allowlist (never a shell). Output bounds + the CLI
    binaries (incl. ``git`` for the BOB-038 ``code_history`` form) are config-tunable
    via ``introspection.*``.
    """
    section = _section(config, "introspection")
    return SubprocessRepoIntrospector(
        PrivacyGuard(repo_root=_REPO_ROOT),
        max_output_chars=_int(
            section, "max_output_chars", _DEFAULT_INTROSPECTION_MAX_OUTPUT_CHARS
        ),
        beadloom_bin=_str(section, "beadloom_bin", "beadloom"),
        bd_bin=_str(section, "bd_bin", "bd"),
        git_bin=_str(section, "git_bin", "git"),
    )
