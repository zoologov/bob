# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure project-health request core (BOB-091.2).

The planner is the security seam of the "как дела у проекта" capability: the model
names WHICH read-only report it wants (from a CLOSED list) and the planner answers with
ONE fixed argv form, every dynamic slot validated. No flag is passed through, so a
hostile ``check`` can never become ``--project`` (another repo), ``prime --update``
(which REWRITES ``AGENTS.md``) or a write subcommand; the ``diff`` git-ref slot is
validated to a strict ref shape before it can reach argv.

🔴 The ``lint`` form carries ``--no-reindex`` because of a LIVE fact: a plain
``beadloom lint`` REINDEXES first, i.e. WRITES the index — measured on this repo. The
form is therefore part of the read-only invariant, not cosmetics.

Pure: request in, form out. One of the two mutation targets of the slice.
"""

from __future__ import annotations

import pytest

from bob.capabilities.introspection.health_form import (
    DEFAULT_DIFF_REF,
    HEALTH_CHECKS,
    is_git_ref,
    plan_health_form,
    validate_git_ref,
)

# --- the closed list of checks -------------------------------------------------


def test_health_checks_is_the_read_only_six() -> None:
    # The tool advertises exactly these to the model, and nothing else is expressible.
    assert set(HEALTH_CHECKS) == {
        "status",
        "prime",
        "doctor",
        "sync-check",
        "lint",
        "diff",
    }


def test_every_advertised_check_actually_plans_a_form() -> None:
    # A check named in the schema but unplannable would be a tool that refuses its own
    # advertised argument.
    for check in HEALTH_CHECKS:
        form = plan_health_form(check)
        assert form.check == check
        assert form.subcommand


@pytest.mark.parametrize(
    ("check", "subcommand", "args"),
    [
        ("status", "status", ()),
        ("prime", "prime", ()),
        ("doctor", "doctor", ()),
        ("sync-check", "sync-check", ()),
    ],
)
def test_the_argument_free_reports_plan_bare_forms(
    check: str, subcommand: str, args: tuple[str, ...]
) -> None:
    form = plan_health_form(check)

    assert form.subcommand == subcommand
    assert form.args == args


# --- 🔴 lint: --no-reindex is a READ-ONLY requirement, --strict makes rc mean it ---


def test_lint_form_never_reindexes() -> None:
    """🔴 A plain ``beadloom lint`` reindexes (writes the index) — measured live."""
    form = plan_health_form("lint")

    assert form.subcommand == "lint"
    assert "--no-reindex" in form.args


def test_lint_form_is_strict_so_the_verdict_is_error_level() -> None:
    # Without --strict the CLI exits 0 even on an error-level violation, so "clean"
    # would be indistinguishable from "broken".
    assert plan_health_form("lint").args == ("--no-reindex", "--strict")


# --- diff: the only form with a dynamic slot ----------------------------------


def test_diff_plans_the_since_form_with_the_given_ref() -> None:
    form = plan_health_form("diff", since="main")

    assert form.subcommand == "diff"
    assert form.args == ("--since", "main")


def test_diff_without_a_ref_defaults_to_head() -> None:
    # One shape only: the flag is always present, so there is no second form to check.
    form = plan_health_form("diff")

    assert form.args == ("--since", DEFAULT_DIFF_REF)
    assert DEFAULT_DIFF_REF == "HEAD"


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_diff_with_a_blank_ref_defaults_to_head(blank: str) -> None:
    # A model that sends an empty string means "not asked", not "a broken ref".
    assert plan_health_form("diff", since=blank).args == ("--since", DEFAULT_DIFF_REF)


def test_a_since_ref_is_ignored_by_the_checks_that_take_no_slot() -> None:
    # ``since`` belongs to ``diff`` alone; smuggling it into another check must not
    # widen that check's form.
    for check in ("status", "prime", "doctor", "sync-check", "lint"):
        form = plan_health_form(check, since="--project")
        assert "--project" not in form.args


# --- check normalisation: a paraphrase answers, a fake value refuses -------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("STATUS", "status"),
        ("  lint  ", "lint"),
        ("Sync-Check", "sync-check"),
        ("sync_check", "sync-check"),
        ("synccheck", "sync-check"),
        ("доки", "sync-check"),
        ("состояние", "status"),
        ("статус", "status"),
        ("контекст", "prime"),
        ("context", "prime"),
        ("здоровье", "doctor"),
        ("health", "doctor"),
        ("доктор", "doctor"),
        ("линт", "lint"),
        ("границы", "lint"),
        ("дифф", "diff"),
        ("изменения", "diff"),
        ("changes", "diff"),
    ],
)
def test_a_paraphrased_check_normalises_to_its_canonical_name(
    raw: str, expected: str
) -> None:
    # The schema advertises the canonical enum, but a model paraphrases; a paraphrase is
    # ANSWERED rather than refused. The canonical name is what the answer is labelled by.
    assert plan_health_form(raw).check == expected


@pytest.mark.parametrize(
    "hostile",
    [
        "reindex",
        "docs generate",
        # 🔴 ``docs`` and ``sync`` are NOT aliases of ``sync-check``: they are the names of
        # WRITE commands of this CLI (``docs generate`` / ``sync-update``), and an alias
        # that reads like a write command is a trap for the next reader.
        "docs",
        "sync",
        "link",
        "init",
        "install-hooks",
        "setup-mcp",
        "active-sync",
        "sync-update",
        "ci",
        "snapshot",
        "tui",
        "watch",
        "mcp-serve",
        "--project",
        "--json",
        "prime --update",
        "status; rm -rf /",
        "",
        "   ",
        "лол что",
    ],
)
def test_a_check_outside_the_closed_list_is_refused(hostile: str) -> None:
    # 🔴 The write commands live in the SAME CLI: an unrecognised check must raise, never
    # be forwarded as a subcommand.
    with pytest.raises(ValueError, match="not a read-only project-health check"):
        plan_health_form(hostile)


# --- the git-ref slot: the only value that reaches argv from the model ----------


@pytest.mark.parametrize(
    "ref",
    [
        "HEAD",
        "HEAD~1",
        "HEAD~10",
        "HEAD^",
        "HEAD^^",
        "main",
        "features/BOB-091",
        "v1.2.3",
        "7edfd7c",
        "0123456789abcdef0123456789abcdef01234567",
        "release_2",
        "fix.me",
    ],
)
def test_a_real_git_ref_is_accepted(ref: str) -> None:
    assert is_git_ref(ref) is True
    assert validate_git_ref(ref) == ref


@pytest.mark.parametrize(
    "hostile",
    [
        "--project",
        "-n",
        "--since",
        "main; rm -rf /",
        "main && echo",
        "main | cat",
        "$(whoami)",
        "`whoami`",
        "main HEAD",
        "main\nHEAD",
        "main\tHEAD",
        "HEAD..main",
        "..",
        "../../etc/passwd",
        "/etc/passwd",
        "main/",
        "/main",
        "main.",
        ".main",
        "main.lock",
        "HEAD@{1}",
        "main{}",
        "main?",
        "main*",
        "main[1]",
        "main~^:x",
        'main"',
        "main'",
        "main\\HEAD",
        "main\x00",
        "",
        "   ",
    ],
)
def test_a_hostile_ref_is_refused(hostile: str) -> None:
    # This value is destined for a git-shaped argument: a flag, a path, a range, a shell
    # metacharacter, whitespace or reflog syntax never gets there.
    assert is_git_ref(hostile) is False
    with pytest.raises(ValueError, match="not a valid git ref"):
        validate_git_ref(hostile)


def test_an_over_long_ref_is_refused() -> None:
    # A real ref is short; a longer value carries no extra signal, only argv surface.
    assert is_git_ref("a" * 100) is False
    with pytest.raises(ValueError, match="not a valid git ref"):
        validate_git_ref("a" * 100)


def test_the_longest_accepted_ref_is_still_accepted() -> None:
    # The bound is inclusive on the legal side, so the check is a real boundary and not
    # an off-by-one that quietly refuses a 40-char sha.
    assert is_git_ref("a" * 64) is True


def test_a_hostile_diff_ref_raises_before_any_form_exists() -> None:
    with pytest.raises(ValueError, match="not a valid git ref"):
        plan_health_form("diff", since="--project")


def test_a_validated_ref_is_returned_verbatim_not_case_folded() -> None:
    # Git refs are case-SENSITIVE (unlike graph ref-ids), so normalising the case here
    # would answer about a different branch.
    assert validate_git_ref("Features/BOB-091") == "Features/BOB-091"


def test_a_ref_is_trimmed_before_validation() -> None:
    assert validate_git_ref("  main  ") == "main"
    assert plan_health_form("diff", since=" main ").args == ("--since", "main")
