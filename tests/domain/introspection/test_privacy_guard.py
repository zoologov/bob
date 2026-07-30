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
# The marker sanitize leaves in place of a scrubbed secret (mirrors the module const).
_REDACTION_MARK = "[REDACTED]"


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


@pytest.mark.parametrize(
    ("secret", "sensitive"),
    [
        ("api_key: sk-abcdefgh12345", "sk-abcdefgh12345"),
        ("API_KEY = deadbeefcafef00d", "deadbeefcafef00d"),
        ("api-key=deadbeefcafef00d", "deadbeefcafef00d"),
        ("token=eyJhbGciOiJ.payload", "eyJhbGciOiJ.payload"),
        ("secret: hunter2hunter2", "hunter2hunter2"),
        ("password = correcthorse", "correcthorse"),
        ("TOKEN: bearer-xyz-1234", "bearer-xyz-1234"),  # case-insensitive keyword
    ],
)
def test_sanitize_redacts_each_secret_keyword_variant(
    guard: PrivacyGuard, secret: str, sensitive: str
) -> None:
    # INV-N4 backstop: every secret-keyword form (api_key/token/secret/password, with
    # ``:`` or ``=``, any case) has its VALUE scrubbed — the literal never leaves.
    out = guard.sanitize(f"prefix {secret} suffix")
    assert sensitive not in out
    assert _REDACTION_MARK in out


def test_sanitize_redacts_sk_token_mid_prose(guard: PrivacyGuard) -> None:
    # A bare ``sk-`` opaque token is scrubbed even without a keyword label.
    out = guard.sanitize("here is a key sk-ABCDEF1234567890abcdef in the log")
    assert "sk-ABCDEF1234567890abcdef" not in out
    assert _REDACTION_MARK in out


def test_sanitize_leaves_ordinary_prose_with_short_words_untouched(
    guard: PrivacyGuard,
) -> None:
    # No over-redaction: prose that merely mentions the word "token" without a
    # ``key: value`` shape is returned unchanged (guards the pattern's precision).
    text = "the auth token is rotated weekly by the ops runbook"
    assert guard.sanitize(text) == text


# --- sanitize: the real .env shapes (BOB-067.6 hotfix — INV-N4 hole) ----------
# The live smoke found sanitize MISSING on the concrete ``.env`` format returned by
# ``read_file`` (leading indentation, dotted ``sk-`` keys, ``__TOKEN``/``_API_KEY``
# names without a word boundary). Fixtures are REAL-SHAPE but SYNTHETIC — never a
# real credential. Each shape's secret VALUE must become ``[REDACTED]`` while the key
# stays readable.

# Synthetic .env line: an indented, double-underscore telegram-token assignment.
_ENV_TELEGRAM = "  ACME_TELEGRAM__TOKEN=1234567890:AAFakeFakeFakeFakeFakeFakeFakeFakeFak"
# Synthetic .env line: an indented Qwen/LLM key whose value carries dots (dotted sk-).
_ENV_LLM_KEY = "  ACME_LLM__API_KEY=sk-zz.AAAA.bbbb.CcccDdddEeeeFfffGgggHhhhIiiiJjjj"


@pytest.mark.parametrize(
    ("line", "sensitive"),
    [
        # 1. indented sensitive-key assignment + ``__TOKEN`` (no word boundary).
        (_ENV_TELEGRAM, "1234567890:AAFakeFakeFakeFakeFakeFakeFakeFakeFak"),
        # 2. indented dotted ``sk-`` value under ``_API_KEY``.
        (_ENV_LLM_KEY, "sk-zz.AAAA.bbbb.CcccDdddEeeeFfffGgggHhhhIiiiJjjj"),
        # 3. lowercase indented sensitive key.
        ("    my_secret = topsecretvalue123", "topsecretvalue123"),
        # 4. ``credential`` / ``auth`` in the key name.
        ("  DB_CREDENTIAL=p4ssw0rd-in-the-clear", "p4ssw0rd-in-the-clear"),
        ("  X_AUTH_HEADER=Bearer-abc123def456", "Bearer-abc123def456"),
    ],
)
def test_sanitize_redacts_indented_env_secret_shapes(
    guard: PrivacyGuard, line: str, sensitive: str
) -> None:
    # The exact shapes the live smoke leaked: indented, underscore-embedded key names.
    out = guard.sanitize(f"contents of .env:\n{line}\ndone")
    assert sensitive not in out
    assert _REDACTION_MARK in out
    # The key label survives — only the value is scrubbed.
    assert "TOKEN" in out or "KEY" in out or "SECRET" in out or "secret" in out or (
        "CREDENTIAL" in out or "AUTH" in out
    )


def test_sanitize_redacts_dotted_sk_token_by_value_shape(guard: PrivacyGuard) -> None:
    # The dotted ``sk-`` shape is scrubbed even WITHOUT a key label (value-shape rule).
    synthetic = "sk-zz.AAAA.bbbb.CcccDdddEeeeFfffGgggHhhhIiiiJjjj"
    out = guard.sanitize(f"leaked token is {synthetic} somewhere")
    assert synthetic not in out
    assert _REDACTION_MARK in out


def test_sanitize_redacts_bare_telegram_token_shape(guard: PrivacyGuard) -> None:
    # A ``digits:base64`` telegram bot-token shape is scrubbed even without any key.
    synthetic = "1234567890:AAFakeFakeFakeFakeFakeFakeFakeFakeFak"
    out = guard.sanitize(f"the value {synthetic} appeared in the log")
    assert synthetic not in out
    assert _REDACTION_MARK in out


def test_sanitize_scrubs_full_env_dump_no_secret_survives(guard: PrivacyGuard) -> None:
    # A whole synthetic .env dump: NO literal secret value survives the backstop.
    dump = (
        "reading .env\n"
        f"{_ENV_TELEGRAM}\n"
        f"{_ENV_LLM_KEY}\n"
        "  ACME_ENV=production\n"
    )
    out = guard.sanitize(dump)
    assert "1234567890:AAFakeFakeFakeFakeFakeFakeFakeFakeFak" not in out
    assert "sk-zz.AAAA.bbbb.CcccDdddEeeeFfffGgggHhhhIiiiJjjj" not in out
    assert _REDACTION_MARK in out


# --- sanitize: over-redaction guard (ordinary code/prose must survive) --------


@pytest.mark.parametrize(
    "ordinary",
    [
        "count = 5",  # non-sensitive lowercase key
        'name = "bob"',  # non-sensitive lowercase key
        "for key in d:\n    print(key)",  # ``key`` used, no ``[:=]``+value
        "if token in seen_tokens:\n    continue",  # ``:`` at EOL, value on next line
        "| key | value |\n|-----|-------|\n| a | 1 |",  # markdown table, no assignment
        "def get_api_key(self) -> str:\n    return self._key",  # identifier only
        "the api key rotation policy is documented in the runbook",  # prose
    ],
)
def test_sanitize_does_not_over_redact_ordinary_code(
    guard: PrivacyGuard, ordinary: str
) -> None:
    # BALANCE: only a secret-NAMED key followed by ``[:=]`` + a non-space same-line
    # value (or a secret value-shape) is masked — code that merely USES the words
    # key/token/secret without assigning them a value is left completely untouched.
    # (SECURITY-FIRST tradeoff, documented in the module: a sensitive-named key that
    # IS assigned an inline value — e.g. ``password = correcthorse`` — is redacted even
    # if the value looks ordinary; under-redacting a real secret is the catastrophic
    # failure, over-redacting a rare code line is cosmetic.)
    assert guard.sanitize(ordinary) == ordinary


def test_sanitize_leaves_ordinary_text_untouched(guard: PrivacyGuard) -> None:
    text = "def handle_message(self) -> None:\n    return None\n"
    assert guard.sanitize(text) == text


def test_sanitize_empty_string(guard: PrivacyGuard) -> None:
    assert guard.sanitize("") == ""


def test_guard_is_frozen(guard: PrivacyGuard) -> None:
    with pytest.raises((AttributeError, TypeError)):
        guard.repo_root = Path("/elsewhere")  # type: ignore[misc]
