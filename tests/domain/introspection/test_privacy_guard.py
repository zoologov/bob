# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure PrivacyGuard DENY-invariant (BOB-017 Phase A .1).

The guard is the single source of truth for "may Bob read this path / return this
text". It is a PURE domain object (no I/O): the tests only build paths and assert
on the deterministic predicate — never touching disk. The invariant must hold by
construction and be impossible to bypass via ``..`` traversal, absolute paths
outside the repo, or denied roots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bob.domain.introspection.privacy_guard import PrivacyGuard

REPO_ROOT = Path("/home/bob/repo")


@pytest.fixture
def guard() -> PrivacyGuard:
    """A guard anchored at a fixed, absolute repo root."""
    return PrivacyGuard(REPO_ROOT)


# --- ALLOW: only the three read-only roots ------------------------------------


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
def test_allows_paths_under_allowed_roots(guard: PrivacyGuard, rel: str) -> None:
    assert guard.allows_path(REPO_ROOT / rel) is True


def test_allows_accepts_relative_path_resolved_against_repo(guard: PrivacyGuard) -> None:
    # A relative path is interpreted against the repo root, not the CWD.
    assert guard.allows_path(Path("src/bob/app.py")) is True


# --- DENY: the personal-data invariant ----------------------------------------


@pytest.mark.parametrize(
    "rel",
    [
        "data/soul/SOUL.md",
        "data/soul/taste_profile.json",
        "data/bob.db",
        "data/bob.db-wal",
        "data/bob.db-shm",
        ".env",
        ".env.local",
        "config/bob.yaml",
        "config/secrets/keys.yaml",
    ],
)
def test_denies_personal_data_paths(guard: PrivacyGuard, rel: str) -> None:
    assert guard.allows_path(REPO_ROOT / rel) is False


@pytest.mark.parametrize(
    "rel",
    [
        "data/anything.txt",  # data/ is not an allowed root
        "README.md",  # repo-root file, not under an allowed root
        "scripts/run.sh",
        "pyproject.toml",
        "src/../config/bob.yaml",  # escapes src into a denied root
        "src/../../etc/passwd",  # escapes the repo entirely
    ],
)
def test_denies_everything_outside_allowed_roots(guard: PrivacyGuard, rel: str) -> None:
    assert guard.allows_path(REPO_ROOT / rel) is False


def test_denies_absolute_path_outside_repo(guard: PrivacyGuard) -> None:
    assert guard.allows_path(Path("/etc/passwd")) is False
    assert guard.allows_path(Path("/home/bob/.ssh/id_rsa")) is False


def test_denies_dotdot_traversal_back_into_repo_denied_root(
    guard: PrivacyGuard,
) -> None:
    # Even a path that *starts* in an allowed root but climbs out is denied.
    sneaky = REPO_ROOT / "src" / ".." / "data" / "soul" / "SOUL.md"
    assert guard.allows_path(sneaky) is False


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
        "data",  # the denied parent root itself
        "config",
        "data/soul",  # the SOUL directory, not just SOUL.md
        "srcfoo/x.py",  # a sibling root that merely *prefixes* an allowed name
        "src_extra/y.py",
    ],
)
def test_denies_lookalike_and_parent_denied_roots(
    guard: PrivacyGuard, rel: str
) -> None:
    # Containment is by path part, not string prefix: ``srcfoo`` is not ``src``.
    assert guard.allows_path(REPO_ROOT / rel) is False


def test_denies_empty_relative_path(guard: PrivacyGuard) -> None:
    # The repo root itself (empty relative) is not an allowed root.
    assert guard.allows_path(Path(".")) is False


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
