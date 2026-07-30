# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure PrivacyGuard containment invariant (BOB-067 full-repo).

The guard is the single source of truth for "may Bob read this path / return this
text". It is a PURE domain object (no I/O): the tests only build paths and assert
on the deterministic predicate — never touching disk. Under BOB-067 the invariant
is full-repo: ANY path resolving under the repo root is allowed (the owner's
deliberate choice — Bob is an equal engineer over his whole repo); the ONLY denial
is an escape past the repo boundary via ``..`` traversal or an absolute path
outside the repo. ``sanitize`` remains the secret-value backstop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bob.capabilities.introspection.privacy_guard import PrivacyGuard

REPO_ROOT = Path("/home/bob/repo")


@pytest.fixture
def guard() -> PrivacyGuard:
    """A guard anchored at a fixed, absolute repo root."""
    return PrivacyGuard(REPO_ROOT)


# --- ALLOW: the whole repo tree (BOB-067 full-repo) ---------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "src/bob/app.py",
        "src/bob/domain/ports.py",
        "tests/domain/test_x.py",
        "docs/architecture.md",
        "src",  # the root dir itself
        "tests",
        "docs",
    ],
)
def test_allows_paths_under_source_roots(guard: PrivacyGuard, rel: str) -> None:
    assert guard.allows_path(REPO_ROOT / rel) is True


@pytest.mark.parametrize(
    "rel",
    [
        ".claude/dev-docs/ROADMAP.md",
        ".claude/dev-docs/VISION.md",
        ".claude/development/docs/features/BOB-017/PRD.md",
        ".claude",  # the bare .claude dir is now readable (full repo)
        ".claude/settings.local.json",
        ".claude/CLAUDE.md",
        ".claude/agents/dev.md",
        ".claude/commands/coordinator.md",
        ".beadloom/_graph/nodes.yml",  # the graph store — the live-bug motivator
        ".beadloom",
    ],
)
def test_allows_all_dot_dirs_under_repo(guard: PrivacyGuard, rel: str) -> None:
    # BOB-067: the whole repo is navigable — .claude and .beadloom included. Bob
    # navigating .beadloom/ was the live bug that motivated this widening.
    assert guard.allows_path(REPO_ROOT / rel) is True


@pytest.mark.parametrize(
    "rel",
    [
        "data/soul/SOUL.md",
        "data/bob.db",
        "config/bob.yaml",
        "config/secrets/keys.yaml",
        ".env",
        ".env.local",
        "data/anything.txt",
        "README.md",  # repo-root file — now readable
        "scripts/run.sh",
        "pyproject.toml",
        "srcfoo/x.py",  # any in-repo sibling is fine now
        "src/../config/bob.yaml",  # resolves to config/ — still under the repo
    ],
)
def test_allows_everything_under_repo_root(guard: PrivacyGuard, rel: str) -> None:
    # The narrow whitelist is gone: any path resolving under the repo root is
    # allowed. Secret *values* are handled separately by ``sanitize`` on output.
    assert guard.allows_path(REPO_ROOT / rel) is True


def test_allows_the_repo_root_itself(guard: PrivacyGuard) -> None:
    # The repo root (empty relative / ``.``) is now allowed so a directory listing
    # of the root can be served.
    assert guard.allows_path(Path(".")) is True
    assert guard.allows_path(REPO_ROOT) is True


def test_allows_accepts_relative_path_resolved_against_repo(guard: PrivacyGuard) -> None:
    # A relative path is interpreted against the repo root, not the CWD.
    assert guard.allows_path(Path("src/bob/app.py")) is True


# --- DENY: only an escape past the repo boundary ------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "../etc/passwd",  # climbs one level out of the repo
        "src/../../etc/passwd",  # escapes the repo entirely
        "../../secret.txt",
    ],
)
def test_denies_dotdot_escape_past_repo(guard: PrivacyGuard, rel: str) -> None:
    assert guard.allows_path(REPO_ROOT / rel) is False


def test_denies_absolute_path_outside_repo(guard: PrivacyGuard) -> None:
    assert guard.allows_path(Path("/etc/passwd")) is False
    assert guard.allows_path(Path("/home/bob/.ssh/id_rsa")) is False


def test_allows_dotdot_that_stays_within_repo(guard: PrivacyGuard) -> None:
    # A path that dips through ``..`` but resolves back UNDER the repo is allowed —
    # containment is about the resolved location, not the literal spelling.
    sneaky = REPO_ROOT / "src" / ".." / "data" / "soul" / "SOUL.md"
    assert guard.allows_path(sneaky) is True


def test_allows_path_is_pure_and_repeatable(guard: PrivacyGuard) -> None:
    p = REPO_ROOT / "src" / "bob" / "app.py"
    assert guard.allows_path(p) == guard.allows_path(p)


def test_allows_collapses_dot_segments(guard: PrivacyGuard) -> None:
    # A ``.`` (current-dir) segment is collapsed purely — the path still lands in src.
    p = REPO_ROOT / "src" / "." / "bob" / "." / "app.py"
    assert guard.allows_path(p) is True


def test_allows_unicode_and_special_chars_within_allowed_root(
    guard: PrivacyGuard,
) -> None:
    # The invariant is about the ROOT, not the leaf name: Unicode / spaces / odd chars
    # under src/ are fine; the guard never inspects file contents or names for secrets.
    assert guard.allows_path(REPO_ROOT / "src" / "файл.py") is True
    assert guard.allows_path(REPO_ROOT / "src" / "a b" / "x-y_z.py") is True


@pytest.mark.parametrize(
    "rel",
    [
        "data",  # every in-repo dir is navigable now
        "config",
        "data/soul",
        "srcfoo/x.py",
        "src_extra/y.py",
    ],
)
def test_allows_sibling_and_data_dirs_under_repo(
    guard: PrivacyGuard, rel: str
) -> None:
    # Under full-repo containment there is no lookalike ambiguity: any in-repo path
    # is allowed. Secrets are redacted from OUTPUT by ``sanitize``, not by hiding paths.
    assert guard.allows_path(REPO_ROOT / rel) is True


# --- sanitize -----------------------------------------------------------------


def test_sanitize_redacts_env_assignments(guard: PrivacyGuard) -> None:
    text = "ok\nTELEGRAM_TOKEN=123:abcDEF\nmore"
    out = guard.sanitize(text)
    assert "123:abcDEF" not in out
    assert "REDACTED" in out
    assert "ok" in out
    assert "more" in out


def test_sanitize_redacts_api_key_like_tokens(guard: PrivacyGuard) -> None:
    text = "use api_key: sk-1234567890ABCDEFmoresecretvalue here"
    out = guard.sanitize(text)
    assert "sk-1234567890ABCDEFmoresecretvalue" not in out
    assert "REDACTED" in out


def test_sanitize_leaves_ordinary_text_untouched(guard: PrivacyGuard) -> None:
    text = "def handle_message(self) -> None:\n    return None\n"
    assert guard.sanitize(text) == text


def test_sanitize_empty_string(guard: PrivacyGuard) -> None:
    assert guard.sanitize("") == ""


def test_guard_is_frozen(guard: PrivacyGuard) -> None:
    with pytest.raises((AttributeError, TypeError)):
        guard.repo_root = Path("/elsewhere")  # type: ignore[misc]
