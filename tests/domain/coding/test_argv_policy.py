# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Юнит-тесты argv-политики интерактивного claude (BOB-087.D1/D2, переезд D4b).

Два чистых ядра :mod:`bob.coding.argv_policy` — сборка argv живого сеанса
(:func:`build_interactive_argv`) и чтение session-id из init-события
(:func:`extract_session_id`). Оба I/O-free и детерминированны, поэтому это ИМЕННО те
domain-юниты, силу которых меряет ``./scripts/mutation.sh coding.argv_policy``: тесты
переехали сюда из ``tests/infrastructure/coding/test_interactive_runner.py`` вместе с
функциями, чтобы у объявленных mutation-целей был ПОСТОЯННЫЙ гейт (конвенция mutmut
исключает ``*/adapters/*``).
"""

from __future__ import annotations

from bob.coding.argv_policy import build_interactive_argv, extract_session_id

# --------------------------------------------------------------------------- #
# build_interactive_argv — сборка argv живого сеанса (BOB-087.D1)
# --------------------------------------------------------------------------- #

_FRESH_ARGV = [
    "claude",
    "-p",
    "--input-format",
    "stream-json",
    "--output-format",
    "stream-json",
    "--verbose",
    "--permission-mode",
    "acceptEdits",
]


def test_build_argv_fresh_is_the_baseline() -> None:
    # OFF path: no resume, no continue → byte-identical to the pre-D1 inline argv.
    assert build_interactive_argv("claude", mode="acceptEdits") == _FRESH_ARGV


def test_build_argv_threads_the_claude_bin_and_mode() -> None:
    argv = build_interactive_argv("my-claude", mode="plan")

    assert argv[0] == "my-claude"
    assert argv[-2:] == ["--permission-mode", "plan"]


def test_build_argv_resume_by_id_appends_resume_flag() -> None:
    argv = build_interactive_argv(
        "claude", mode="acceptEdits", resume_session_id="sess-123"
    )

    # The fresh baseline is preserved, then ``--resume <id>`` is appended.
    assert argv[: len(_FRESH_ARGV)] == _FRESH_ARGV
    assert argv[len(_FRESH_ARGV) :] == ["--resume", "sess-123"]


def test_build_argv_continue_appends_continue_flag() -> None:
    argv = build_interactive_argv("claude", mode="acceptEdits", continue_session=True)

    assert argv[: len(_FRESH_ARGV)] == _FRESH_ARGV
    assert argv[len(_FRESH_ARGV) :] == ["--continue"]


def test_build_argv_resume_by_id_takes_precedence_over_continue() -> None:
    argv = build_interactive_argv(
        "claude",
        mode="acceptEdits",
        resume_session_id="sess-9",
        continue_session=True,
    )

    # A concrete session id is more specific than "continue the latest" — it wins,
    # and ``--continue`` is NOT also emitted (never two resume strategies at once).
    assert argv[len(_FRESH_ARGV) :] == ["--resume", "sess-9"]
    assert "--continue" not in argv


def test_build_argv_empty_resume_id_is_treated_as_no_resume() -> None:
    # An empty id is not a real session — fall back to the fresh baseline (no --resume).
    assert build_interactive_argv("claude", mode="plan", resume_session_id="") == [
        "claude",
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "plan",
    ]


# --------------------------------------------------------------------------- #
# build_interactive_argv — owner-only --add-dir relaxation (BOB-087.D2)
# --------------------------------------------------------------------------- #


def test_build_argv_without_extra_dirs_is_the_fresh_baseline() -> None:
    # OFF path (BOB-087.D2): no extra dirs configured → nothing appended at all.
    assert build_interactive_argv("claude", mode="acceptEdits", extra_dirs=()) == (
        _FRESH_ARGV
    )


def test_build_argv_appends_add_dir_after_the_head() -> None:
    argv = build_interactive_argv(
        "claude", mode="acceptEdits", extra_dirs=["/srv/docs", "/srv/spec"]
    )

    assert argv == [
        *_FRESH_ARGV,
        "--add-dir",
        "/srv/docs",
        "--add-dir",
        "/srv/spec",
    ]


def test_build_argv_appends_add_dir_after_the_resume_flag() -> None:
    argv = build_interactive_argv(
        "claude",
        mode="acceptEdits",
        resume_session_id="sess-3",
        extra_dirs=["/srv/docs"],
    )

    # Documented order: resumption strategy first, then the --add-dir pairs.
    assert argv == [*_FRESH_ARGV, "--resume", "sess-3", "--add-dir", "/srv/docs"]


def test_build_argv_appends_add_dir_after_the_continue_flag() -> None:
    argv = build_interactive_argv(
        "claude", mode="acceptEdits", continue_session=True, extra_dirs=["/srv/docs"]
    )

    assert argv == [*_FRESH_ARGV, "--continue", "--add-dir", "/srv/docs"]


def test_build_argv_sanitises_a_flag_shaped_extra_dir() -> None:
    # 🔴 argv injection: a "--…" entry would land in an argv slot as a claude FLAG.
    argv = build_interactive_argv(
        "claude",
        mode="acceptEdits",
        extra_dirs=["--dangerously-skip-permissions", "", "/srv/docs"],
    )

    assert argv == [*_FRESH_ARGV, "--add-dir", "/srv/docs"]


# --------------------------------------------------------------------------- #
# extract_session_id — чтение id из init-события (BOB-087.D1)
# --------------------------------------------------------------------------- #


def test_extract_session_id_reads_the_init_event() -> None:
    event = {"type": "system", "subtype": "init", "session_id": "sess-abc"}

    assert extract_session_id(event) == "sess-abc"


def test_extract_session_id_ignores_a_non_init_system_event() -> None:
    assert (
        extract_session_id({"type": "system", "subtype": "other", "session_id": "x"})
        is None
    )


def test_extract_session_id_ignores_a_non_system_event() -> None:
    assert extract_session_id({"type": "assistant", "session_id": "x"}) is None


def test_extract_session_id_missing_field_is_none() -> None:
    assert extract_session_id({"type": "system", "subtype": "init"}) is None


def test_extract_session_id_non_str_field_is_none() -> None:
    assert (
        extract_session_id({"type": "system", "subtype": "init", "session_id": 123})
        is None
    )


def test_extract_session_id_empty_str_is_none() -> None:
    assert (
        extract_session_id({"type": "system", "subtype": "init", "session_id": ""})
        is None
    )
