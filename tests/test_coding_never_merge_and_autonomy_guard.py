# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 Structural safety guards for BOB-039 — never-merge / never-main / not-autonomous.

These are *whole-feature* invariants the per-module tests cannot express:

* US-4 (never merge / never main): the :class:`PullRequestOpener` port has no merge
  surface, the live ``GhPullRequestOpener`` exposes only ``open``, and NO BOB-039
  source file contains a merge / push-to-main code path. The only PR action that can
  exist is opening one.
* US-7 (off by default / not autonomous): the coding assistant is built ONLY when the
  owner switches ``coder.enabled`` on (default off → ``None``), and it is never placed
  on the autonomous capability path (``goals.safe_capabilities`` stays empty, and the
  coder config never injects a capability there).

All of this is asserted WITHOUT spawning ``claude`` / ``gh`` / ``git``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import bob.coding.adapters.gh_pr as gh_mod
import bob.coding.usecases.coding_assistant as ca_mod
from bob.app import _build_safe_capabilities
from bob.coding import ports
from bob.coding.adapters.gh_pr import GhPullRequestOpener
from bob.infrastructure.config.loader import DEFAULT_CONFIG

# Source files that make up the BOB-039 coding feature.
_BOB039_SOURCE = (
    "src/bob/coding/state.py",
    "src/bob/coding/entities.py",
    "src/bob/coding/naming.py",
    "src/bob/coding/narrate.py",
    "src/bob/coding/adapters/git_worktree.py",
    "src/bob/coding/adapters/gh_pr.py",
    "src/bob/coding/adapters/claude_runner.py",
    "src/bob/coding/adapters/_exec.py",
    "src/bob/coding/adapters/_branch.py",
    "src/bob/coding/usecases/coding_assistant.py",
    # BOB-089.A: the workplace became substitutable (linked worktree OR a separate
    # clone), so the second adapter and the shared integration step are inside the
    # invariant too — otherwise the guard would cover only half of the ways Bob can
    # reach a remote.
    "src/bob/coding/clone_plan.py",
    "src/bob/coding/adapters/git_clone.py",
    "src/bob/coding/adapters/_integrate.py",
    "src/bob/coding/adapters/_paths.py",
)

# The two interchangeable workplace adapters (BOB-089.A). Both realise the same ports,
# so the never-push-main invariant has to hold for BOTH — a new workplace that forgot
# the branch validation would be a hole exactly the size of the feature.
_WORKPLACE_ADAPTERS = (
    "src/bob/coding/adapters/git_worktree.py",
    "src/bob/coding/adapters/git_clone.py",
)

# argv fragments that would constitute a merge path. Bob must never build any of these
# — he opens a PR and stops. (A ``git push`` of the validated ``bob/<slug>`` feature
# branch IS allowed since BOB-040 — see the dedicated never-push-main guard below.)
_FORBIDDEN_ARGV = (
    '"merge"',
    "'merge'",
    "pr merge",
)


def _repo_root() -> Path:
    # tests/ -> repo root
    return Path(__file__).resolve().parent.parent


# --- US-4: the PR port has no merge surface -------------------------------------


def test_pull_request_opener_port_has_only_open_no_merge() -> None:
    assert hasattr(ports.PullRequestOpener, "open")
    # 🔴 No merge method on the port — the absence IS the safety invariant.
    assert not hasattr(ports.PullRequestOpener, "merge")


def test_gh_opener_exposes_open_only_no_merge_or_push() -> None:
    public = {name for name in dir(GhPullRequestOpener) if not name.startswith("_")}
    assert "open" in public
    for forbidden in ("merge", "push", "land", "approve"):
        assert forbidden not in public, f"GhPullRequestOpener must not expose {forbidden!r}"


# --- US-4: no merge / push-to-main code path anywhere in the feature ------------


@pytest.mark.parametrize("rel", _BOB039_SOURCE)
def test_no_source_file_builds_a_merge_or_push_main_argv(rel: str) -> None:
    text = (_repo_root() / rel).read_text(encoding="utf-8")
    # 'main' may appear in prose/branch-base; what must NOT appear is a built argv
    # fragment that pushes or merges. Comments/docstrings warn AGAINST it, so we look
    # for the executable argv tokens specifically.
    for fragment in _FORBIDDEN_ARGV:
        assert fragment not in text, f"{rel} contains a forbidden argv fragment {fragment!r}"


def test_the_only_push_form_pushes_the_branch_variable_from_one_place() -> None:
    # 🔴 BOB-040 + BOB-089.A: the deterministic commit+push lives in EXACTLY ONE module
    # (``_integrate.py``, shared by both workplace adapters) and pushes the validated
    # ``bob/<slug>`` branch VARIABLE — never a literal trunk token. One place is part of
    # the invariant: a second copy is a second thing to keep honest.
    text = (_repo_root() / "src/bob/coding/adapters/_integrate.py").read_text(
        encoding="utf-8"
    )
    assert '"origin", branch' in text
    assert '"main"' not in text  # no literal main argv token
    assert "'main'" not in text
    others = [
        rel
        for rel in _BOB039_SOURCE
        if rel != "src/bob/coding/adapters/_integrate.py"
        and '"push"' in (_repo_root() / rel).read_text(encoding="utf-8")
    ]
    assert others == [], f"a second push argv appeared in {others}"


@pytest.mark.parametrize("rel", _WORKPLACE_ADAPTERS)
def test_every_workplace_adapter_validates_the_branch_before_pushing(rel: str) -> None:
    # Both adapters re-validate the branch (``is_safe_branch``) before any git runs, so
    # there is physically no path that pushes the trunk from either workplace.
    text = (_repo_root() / rel).read_text(encoding="utf-8")
    assert "is_safe_branch" in text
    assert '"main"' not in text  # no literal main argv token
    assert "'main'" not in text


def test_pr_command_is_create_only_with_main_as_base_not_a_push() -> None:
    # The gh adapter's argv is `gh pr create --base main ...` — `main` is only ever the
    # PR BASE (where the owner will land it), never a push/checkout target.
    text = (_repo_root() / "src/bob/coding/adapters/gh_pr.py").read_text(
        encoding="utf-8"
    )
    assert '"create"' in text or "'create'" in text or "pr create" in text
    # No `git push` orchestration here — the opener only opens.
    assert "push" not in gh_mod.__dict__  # sanity: module namespace has no push helper


# --- US-7: off by default → the assistant is not built --------------------------


def test_coder_disabled_by_default_in_shipped_config() -> None:
    coder = DEFAULT_CONFIG["coder"]
    assert isinstance(coder, dict)
    assert coder["enabled"] is False  # 🔴 conservative default: Bob does not drive code


# --- US-7: never on the autonomous capability path ------------------------------


def test_default_safe_capabilities_is_empty() -> None:
    # The autonomous allowlist is empty by default — nothing self-triggers.
    assert _build_safe_capabilities(DEFAULT_CONFIG) == ()


def test_enabling_coder_never_injects_a_capability_into_safe_allowlist() -> None:
    # Even with the coder switched fully on, the autonomous allowlist is untouched:
    # the coding assistant is a use-case, NOT a registered capability, so it can never
    # ride the self-directed goal tick.
    config = {
        "coder": {"enabled": True, "permission_mode": "acceptEdits"},
        "goals": {"safe_capabilities": ["recall_memory"]},
    }
    allow = _build_safe_capabilities(config)
    assert allow == ("recall_memory",)
    for name in allow:
        assert "cod" not in name.lower()
        assert "claude" not in name.lower()
        assert "pr" not in name.lower().split("_")


def test_coding_assistant_is_not_referenced_by_the_registry_builder() -> None:
    # Structural guard: the capability-registry builder never touches the coding
    # assistant (it is wired separately, off the autonomous path).
    registry_src = (
        _repo_root() / "src/bob/runtime/wiring/capabilities.py"
    ).read_text(encoding="utf-8")
    builder = registry_src.split("def _build_registry")[1].split("\ndef ")[0]
    assert "coding_assistant" not in builder
    assert "CodingAssistant" not in builder
    # The use-case module itself registers nothing into a capability registry.
    assert "registry" not in ca_mod.__dict__
