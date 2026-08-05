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
    _ALIASES,
    _FIXED_FORMS,
    _GIT_REF_RE,
    _MAX_REF_CHARS,
    _REF_FORBIDDEN_SUBSTRINGS,
    _REF_FORBIDDEN_SUFFIXES,
    _SINCE_FLAG,
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


# --- 🔴 the module-level VALUES (BOB-091.4, review Major-1) ----------------------
#
# Measured, not assumed: `scripts/mutation.sh` copies this module into its sandbox and
# mutates FUNCTION BODIES only — HEALTH_CHECKS, _FIXED_FORMS (including the
# ``('--no-reindex', '--strict')`` tuple), _ALIASES, both regexes and _MAX_REF_CHARS came
# through byte-for-byte, with zero mutants. So the whole argv guard of this seam is
# constant data that the mutation score says NOTHING about — and BOB-091.4's Critical-1
# lived in exactly such a constant. These tests are the gate on the VALUES.


def test_the_advertised_checks_are_unique_and_ordered_as_the_tool_lists_them() -> None:
    assert HEALTH_CHECKS == ("status", "prime", "doctor", "sync-check", "lint", "diff")
    assert len(set(HEALTH_CHECKS)) == len(HEALTH_CHECKS)


@pytest.mark.parametrize(
    "write_command",
    [
        "reindex",
        "docs",
        "snapshot",
        "link",
        "init",
        "install-hooks",
        "setup-rules",
        "setup-mcp",
        "setup-agentic-flow",
        "setup-branch-protection",
        "setup-ai-techwriter",
        "active-sync",
        "sync-update",
        "ci",
        "federate",
        "export",
    ],
)
def test_no_write_command_of_the_same_cli_is_an_advertised_check(
    write_command: str,
) -> None:
    # 🔴 The closed list IS the guard: a write command sitting in it would be a write Bob
    # could ask for by name.
    assert write_command not in HEALTH_CHECKS
    assert write_command not in _ALIASES


def test_every_fixed_form_belongs_to_an_advertised_check() -> None:
    # A form for a check nobody can ask for is dead surface; a check without a form would
    # be an advertised argument the tool refuses. ``diff`` is the one deliberate absence —
    # its form carries a slot and is built, not stored.
    assert set(_FIXED_FORMS) == set(HEALTH_CHECKS) - {"diff"}


def test_the_lint_form_is_exactly_the_two_flags_that_make_the_read_honest() -> None:
    # 🔴 --no-reindex: a plain ``beadloom lint`` WRITES the index (measured live).
    # --strict: without it the CLI exits 0 even on an error-level violation.
    assert _FIXED_FORMS["lint"] == ("--no-reindex", "--strict")


def test_no_fixed_form_carries_a_flag_that_widens_the_read() -> None:
    # The forms are the reason ``--project <other repo>``, ``--json`` and the AGENTS.md
    # rewriting ``prime --update`` are INEXPRESSIBLE. A single extra flag in this table
    # would open all of it — and no mutant would ever have told us.
    forbidden = ("--project", "--json", "--update", "--format", "--report", "--fail-if")
    for check, args in _FIXED_FORMS.items():
        assert all(flag not in args for flag in forbidden), check
    assert _FIXED_FORMS["status"] == ()
    assert _FIXED_FORMS["prime"] == ()
    assert _FIXED_FORMS["doctor"] == ()
    assert _FIXED_FORMS["sync-check"] == ()


def test_every_alias_resolves_onto_an_advertised_check() -> None:
    # An alias pointing at anything else would be a new expressible value smuggled in
    # through the paraphrase table.
    for alias, canonical in _ALIASES.items():
        assert canonical in HEALTH_CHECKS, alias


def test_every_alias_key_is_already_normalised() -> None:
    # Lookup happens AFTER strip().lower(), so a key with capitals or spaces would be
    # dead: the paraphrase would silently stop being answered.
    for alias in _ALIASES:
        assert alias == alias.strip().lower()


def test_no_alias_shadows_a_canonical_name() -> None:
    assert not set(_ALIASES) & set(HEALTH_CHECKS)


def test_the_ref_length_bound_fits_a_full_sha_and_nothing_absurd() -> None:
    # The value has to sit above the longest REAL ref (a 40-char sha) and well below the
    # length at which a "ref" is just argv surface.
    assert _MAX_REF_CHARS >= 40
    assert _MAX_REF_CHARS == 64


def test_the_ref_pattern_is_anchored_at_both_ends() -> None:
    # 🔴 An unanchored pattern would match a hostile value's harmless PREFIX — the classic
    # way an injection guard passes its own tests and still lets the value through. And the
    # end anchor is ``\Z``, not ``$``: ``$`` tolerates a trailing newline, which would make
    # this guard depend on the caller stripping (found here, BOB-091.4).
    assert _GIT_REF_RE.pattern.startswith("^")
    assert _GIT_REF_RE.pattern.endswith(r"\Z")
    assert _GIT_REF_RE.match("main\n") is None


@pytest.mark.parametrize(
    "char",
    [
        ";", "|", "&", "$", "`", ">", "<", "(", ")", "{", "}", "[", "]", "!", "*",
        "?", "'", '"', "\\", " ", "\t", "\n", "\r", "\x00", ",", "=", "@", "#", "%",
        "+", ":",
    ],
)
def test_the_ref_pattern_admits_no_shell_or_glob_character(char: str) -> None:
    # Asserted on the PATTERN itself, per character, because this class is the injection
    # guard of the only model-chosen value that reaches argv on this path.
    assert _GIT_REF_RE.match(f"main{char}") is None
    assert _GIT_REF_RE.match(f"{char}main") is None


@pytest.mark.parametrize("first", ["-", ".", "/", "~", "^"])
def test_the_ref_pattern_refuses_a_leading_separator(first: str) -> None:
    # A leading ``-`` would be a FLAG; a leading ``/`` or ``.`` is a path, not a ref.
    assert _GIT_REF_RE.match(f"{first}main") is None


def test_the_refused_ref_shapes_mirror_gits_own_refname_rules() -> None:
    # These are the shapes that PASS the character class and are still illegal: a range is
    # two refs, a trailing separator is malformed, ``.lock`` is reserved.
    assert ".." in _REF_FORBIDDEN_SUBSTRINGS
    assert set(_REF_FORBIDDEN_SUFFIXES) == {"/", ".", ".lock"}


def test_the_diff_slot_is_the_since_flag_and_its_default_is_a_valid_ref() -> None:
    assert _SINCE_FLAG == "--since"
    assert is_git_ref(DEFAULT_DIFF_REF) is True
