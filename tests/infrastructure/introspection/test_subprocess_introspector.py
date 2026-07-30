# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for SubprocessRepoIntrospector (BOB-017 Phase A .1).

The adapter realises :class:`bob.domain.ports.RepoIntrospector` by shelling out to
local ``beadloom`` / ``bd`` via ``asyncio.create_subprocess_exec`` (NEVER a shell)
against a FIXED allowlist of read-only subcommands, and reading source files only
after the :class:`~bob.capabilities.introspection.privacy_guard.PrivacyGuard` allows the
path. The subprocess boundary is injected as a fake here so the tests are
deterministic and never actually spawn a process; the file reader runs against a
tmp repo layout.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from bob.capabilities.adapters.introspection.subprocess_introspector import (
    _FIND_FILE_MAX_RESULTS,
    DeniedPathError,
    DisallowedCommandError,
    SubprocessRepoIntrospector,
    _ExecRunner,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard


class _FakeRunner:
    """Records the argv it was asked to run and returns canned stdout."""

    def __init__(self, stdout: str = "ok-output", *, delay: float = 0.0) -> None:
        self.calls: list[list[str]] = []
        self.seen_timeout: float = 0.0
        self._stdout = stdout
        self._delay = delay

    async def __call__(self, argv: list[str], *, timeout: float) -> str:
        self.seen_timeout = timeout
        self.calls.append(list(argv))
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._stdout


class _SeqRunner:
    """Returns canned stdout keyed by the subcommand of each argv (for fallbacks)."""

    def __init__(self, by_subcommand: dict[str, str]) -> None:
        self.calls: list[list[str]] = []
        self._by_subcommand = by_subcommand

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        self.calls.append(list(argv))
        # argv is [bin, subcommand, *args]; key on the subcommand.
        return self._by_subcommand.get(argv[1], "")


def _make(
    tmp_path: Path,
    runner: _FakeRunner | _SeqRunner,
    *,
    max_output_chars: int = 10_000,
    timeout: float = 5.0,
) -> SubprocessRepoIntrospector:
    return SubprocessRepoIntrospector(
        PrivacyGuard(tmp_path),
        runner=runner,
        max_output_chars=max_output_chars,
        timeout=timeout,
        beadloom_bin="beadloom",
        bd_bin="bd",
    )


# --- allowlist enforcement ----------------------------------------------------


@pytest.mark.asyncio
async def test_architecture_context_runs_beadloom_ctx(tmp_path: Path) -> None:
    # An exact node-id shape (here a bead id) routes to ``beadloom ctx``.
    runner = _FakeRunner("graph-ctx")
    intro = _make(tmp_path, runner)

    out = await intro.architecture_context("bob-031")

    assert out == "graph-ctx"
    assert runner.calls == [["beadloom", "ctx", "bob-031"]]


@pytest.mark.asyncio
async def test_architecture_context_free_text_routes_to_search(tmp_path: Path) -> None:
    # A natural-language question is not a graph ref-id -> beadloom search grounds it.
    runner = _FakeRunner("search-hits")
    intro = _make(tmp_path, runner)

    out = await intro.architecture_context("как устроена память")

    assert out == "search-hits"
    assert runner.calls == [["beadloom", "search", "как устроена память"]]


@pytest.mark.asyncio
async def test_architecture_context_ref_id_routes_to_ctx(tmp_path: Path) -> None:
    # A bead/node-id shape (bob-..., word.py, word.md) is an exact graph ref -> ctx.
    for ref in ("bob-1av", "subprocess_introspector.py", "architecture.md"):
        runner = _FakeRunner("ctx-out")
        intro = _make(tmp_path, runner)

        out = await intro.architecture_context(ref)

        assert out == "ctx-out"
        assert runner.calls == [["beadloom", "ctx", ref]]


@pytest.mark.asyncio
async def test_architecture_context_falls_back_ctx_to_search_when_empty(
    tmp_path: Path,
) -> None:
    # A ref-id-shaped query that ctx cannot resolve still grounds via search.
    runner = _SeqRunner({"ctx": "", "search": "search-grounded"})
    intro = _make(tmp_path, runner)

    out = await intro.architecture_context("bob-missing")

    assert out == "search-grounded"
    assert runner.calls == [
        ["beadloom", "ctx", "bob-missing"],
        ["beadloom", "search", "bob-missing"],
    ]


@pytest.mark.asyncio
async def test_architecture_context_free_text_no_fallback_when_search_empty(
    tmp_path: Path,
) -> None:
    # Free text already goes straight to search; an empty search is not retried via ctx.
    runner = _SeqRunner({"search": ""})
    intro = _make(tmp_path, runner)

    out = await intro.architecture_context("совершенно неизвестная штука")

    assert out == ""
    assert runner.calls == [["beadloom", "search", "совершенно неизвестная штука"]]


@pytest.mark.asyncio
async def test_search_code_runs_beadloom_search(tmp_path: Path) -> None:
    runner = _FakeRunner("hits")
    intro = _make(tmp_path, runner)

    await intro.search_code("privacy guard")

    assert runner.calls == [["beadloom", "search", "privacy guard"]]


@pytest.mark.asyncio
async def test_list_tasks_runs_bd_ready(tmp_path: Path) -> None:
    runner = _FakeRunner("ready-beads")
    intro = _make(tmp_path, runner)

    await intro.list_tasks("")

    assert runner.calls == [["bd", "ready"]]


@pytest.mark.asyncio
async def test_list_tasks_with_id_runs_bd_show(tmp_path: Path) -> None:
    runner = _FakeRunner("bead-detail")
    intro = _make(tmp_path, runner)

    await intro.list_tasks("bob-9eh")

    assert runner.calls == [["bd", "show", "bob-9eh"]]


@pytest.mark.asyncio
async def test_list_tasks_ready_keyword_runs_bd_ready(tmp_path: Path) -> None:
    for query in ("ready", "готовые задачи", "что готово"):
        runner = _FakeRunner("ready-beads")
        intro = _make(tmp_path, runner)

        await intro.list_tasks(query)

        assert runner.calls == [["bd", "ready"]]


@pytest.mark.asyncio
async def test_list_tasks_closed_keyword_runs_bd_list_closed(tmp_path: Path) -> None:
    for query in ("закрытые", "недавние задачи", "recent", "история", "closed tasks"):
        runner = _FakeRunner("closed-beads")
        intro = _make(tmp_path, runner)

        await intro.list_tasks(query)

        assert runner.calls == [["bd", "list", "--status", "closed"]]


@pytest.mark.asyncio
async def test_list_tasks_in_progress_keyword_runs_bd_list_in_progress(
    tmp_path: Path,
) -> None:
    for query in ("в работе", "in progress", "in-progress"):
        runner = _FakeRunner("wip-beads")
        intro = _make(tmp_path, runner)

        await intro.list_tasks(query)

        assert runner.calls == [["bd", "list", "--status", "in_progress"]]


@pytest.mark.asyncio
async def test_list_tasks_all_keyword_runs_bd_list_unfiltered(tmp_path: Path) -> None:
    for query in ("все задачи", "all tasks", "весь список"):
        runner = _FakeRunner("all-beads")
        intro = _make(tmp_path, runner)

        await intro.list_tasks(query)

        assert runner.calls == [["bd", "list"]]


@pytest.mark.asyncio
async def test_list_tasks_free_text_no_id_falls_back_to_unfiltered_list(
    tmp_path: Path,
) -> None:
    # A free-text tracker query with no id and no listing keyword falls back to the
    # unfiltered ``bd list`` rather than a doomed ``bd show`` on prose (line 236).
    runner = _FakeRunner("all-beads")
    intro = _make(tmp_path, runner)

    await intro.list_tasks("покажи чем ты занят сегодня")

    assert runner.calls == [["bd", "list"]]


@pytest.mark.asyncio
async def test_list_tasks_status_token_is_allowlist_validated(tmp_path: Path) -> None:
    # The bd-list status forms go through the read allowlist (no raw flag passthrough):
    # an arbitrary flag is still refused, proving the no-arbitrary-args invariant holds.
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("bd", "list", "--status", "closed; rm -rf /")

    assert runner.calls == []


@pytest.mark.asyncio
async def test_runner_never_invoked_for_disallowed_command(tmp_path: Path) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("beadloom", "init")  # not on the read allowlist

    assert runner.calls == []  # refused, NOT executed


@pytest.mark.asyncio
async def test_disallowed_binary_is_refused(tmp_path: Path) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    with pytest.raises(DisallowedCommandError):
        await intro._run("rm", "ready")

    assert runner.calls == []


@pytest.mark.asyncio
async def test_argument_flags_that_could_inject_are_refused(tmp_path: Path) -> None:
    runner = _FakeRunner()
    intro = _make(tmp_path, runner)

    # A flag-looking arg must never be passed through to a subcommand.
    with pytest.raises(DisallowedCommandError):
        await intro._run("bd", "show", "--exec=rm -rf /")

    assert runner.calls == []


# --- denoise: strip bd/beadloom tooling tip + setup-hint tail -----------------


@pytest.mark.asyncio
async def test_tip_tail_is_stripped(tmp_path: Path) -> None:
    raw = (
        "○ bob-1av ● P1 [bug] real task\n"
        "\n"
        "Total: 50 issues (0 open, 0 in progress)\n"
        "\n"
        "Status: ○ open  ◐ in_progress  ● blocked  ✓ closed  ❄ deferred\n"
        "\n"
        "💡 Tip: install the GitHub plugin for richer output\n"
    )
    runner = _FakeRunner(raw)
    intro = _make(tmp_path, runner)

    out = await intro.list_tasks("закрытые")

    assert "bob-1av" in out
    assert "Total: 50 issues" in out
    assert "💡" not in out
    assert "Tip:" not in out
    assert "Status: ○ open" not in out


@pytest.mark.asyncio
async def test_limit_hint_tail_is_stripped(tmp_path: Path) -> None:
    raw = (
        "○ bob-1av real task\n"
        "Showing 50 issues; more results matched but were hidden by --limit. "
        "Use --limit 0 for all, or --limit N to raise the cap.\n"
    )
    runner = _FakeRunner(raw)
    intro = _make(tmp_path, runner)

    out = await intro.list_tasks("все")

    assert "bob-1av" in out
    assert "Showing 50 issues" not in out
    assert "--limit" not in out


@pytest.mark.asyncio
async def test_denoise_keeps_real_content_only(tmp_path: Path) -> None:
    # A pure-content body with no tip tail is returned unchanged (no over-stripping).
    runner = _FakeRunner("○ bob-1av real task\n○ bob-2bc another task")
    intro = _make(tmp_path, runner)

    out = await intro.list_tasks("все")

    assert out == "○ bob-1av real task\n○ bob-2bc another task"


# --- output truncation + sanitization -----------------------------------------


@pytest.mark.asyncio
async def test_output_is_truncated_to_cap(tmp_path: Path) -> None:
    runner = _FakeRunner("x" * 5000)
    intro = _make(tmp_path, runner, max_output_chars=100)

    out = await intro.architecture_context("bob")

    assert len(out) <= 100 + 64  # cap + a short truncation marker
    assert out.startswith("x" * 100)


@pytest.mark.asyncio
async def test_output_is_sanitized(tmp_path: Path) -> None:
    runner = _FakeRunner("TELEGRAM_TOKEN=123:abcDEF\nrest")
    intro = _make(tmp_path, runner)

    out = await intro.list_tasks("")

    assert "123:abcDEF" not in out
    assert "REDACTED" in out


# --- timeout wiring -----------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_is_passed_to_runner(tmp_path: Path) -> None:
    runner = _FakeRunner("ok")
    intro = SubprocessRepoIntrospector(
        PrivacyGuard(tmp_path), runner=runner, timeout=2.5
    )

    await intro.architecture_context("bob")

    assert runner.seen_timeout == 2.5


# --- read_file via the guard --------------------------------------------------


@pytest.mark.asyncio
async def test_read_file_reads_allowed_source(tmp_path: Path) -> None:
    src = tmp_path / "src" / "bob" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("line1\nline2\nline3\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/bob/app.py", max_lines=2)

    assert "line1" in out
    assert "line2" in out
    assert "line3" not in out  # capped at max_lines


@pytest.mark.asyncio
async def test_read_file_reads_roadmap_under_dev_docs(tmp_path: Path) -> None:
    # BOB-034: the curation-vision docs under .claude/dev-docs are now readable.
    roadmap = tmp_path / ".claude" / "dev-docs" / "ROADMAP.md"
    roadmap.parent.mkdir(parents=True)
    roadmap.write_text("# Roadmap\nP0\nP1\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file(".claude/dev-docs/ROADMAP.md", max_lines=10)

    assert "Roadmap" in out


@pytest.mark.asyncio
async def test_read_file_reads_feature_spec_under_development_docs(
    tmp_path: Path,
) -> None:
    # BOB-034: feature PRD/RFC/CONTEXT specs under .claude/development/docs read too.
    prd = tmp_path / ".claude" / "development" / "docs" / "features" / "X" / "PRD.md"
    prd.parent.mkdir(parents=True)
    prd.write_text("# PRD\nrequirements\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file(
        ".claude/development/docs/features/X/PRD.md", max_lines=10
    )

    assert "requirements" in out


@pytest.mark.asyncio
async def test_read_file_reads_settings_under_dot_claude(tmp_path: Path) -> None:
    # BOB-067: full-repo access — the rest of .claude/ (settings etc.) is readable now.
    settings = tmp_path / ".claude" / "settings.local.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"editor": "vim"}', encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file(".claude/settings.local.json", max_lines=10)

    assert "editor" in out


@pytest.mark.asyncio
async def test_read_file_reads_data_soul_under_full_repo(
    tmp_path: Path,
) -> None:
    # BOB-067: full-repo access — data/soul is readable now (owner's deliberate
    # choice). Secret *values* are still redacted by ``sanitize`` (see below).
    soul = tmp_path / "data" / "soul" / "SOUL.md"
    soul.parent.mkdir(parents=True)
    soul.write_text("# SOUL\nordinary prose\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("data/soul/SOUL.md", max_lines=100)

    assert "ordinary prose" in out


@pytest.mark.asyncio
async def test_read_file_reads_beadloom_graph_store(tmp_path: Path) -> None:
    # 🔴 The live-bug motivator: navigating .beadloom/ must now succeed, not confabulate.
    node = tmp_path / ".beadloom" / "_graph" / "nodes.yml"
    node.parent.mkdir(parents=True)
    node.write_text("nodes:\n  - id: bob\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file(".beadloom/_graph/nodes.yml", max_lines=100)

    assert "bob" in out


@pytest.mark.asyncio
async def test_read_file_redacts_env_secret_value(tmp_path: Path) -> None:
    # BOB-067: the .env file is readable now, but the secret VALUE is redacted on
    # output by ``sanitize`` — full-repo read is not a secret leak (INV-N4).
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_TOKEN=should-never-leak", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file(".env", max_lines=100)

    assert "should-never-leak" not in out
    assert "REDACTED" in out


@pytest.mark.asyncio
async def test_read_file_sanitizes_returned_content(tmp_path: Path) -> None:
    src = tmp_path / "src" / "leaky.py"
    src.parent.mkdir(parents=True)
    src.write_text("API_KEY=sk-abcdef0123456789secret\ncode = 1\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/leaky.py", max_lines=10)

    assert "sk-abcdef0123456789secret" not in out
    assert "REDACTED" in out


@pytest.mark.asyncio
async def test_read_file_missing_allowed_file_returns_refusal(tmp_path: Path) -> None:
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/does_not_exist.py", max_lines=10)

    assert "not found" in out.lower()


@pytest.mark.asyncio
async def test_read_file_on_directory_returns_refusal(tmp_path: Path) -> None:
    # An allowed path that is a directory must not raise — honest refusal instead.
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/pkg", max_lines=10)

    assert "not found" in out.lower()


# --- 🔴 privacy invariant: only an escape PAST the repo is refused (BOB-067) ----


@pytest.mark.asyncio
async def test_read_file_reads_symlink_staying_within_repo(
    tmp_path: Path,
) -> None:
    # BOB-067: a symlink whose REAL path stays inside the repo reads normally — even
    # a link from src into data/soul, since the whole repo is readable now.
    soul = tmp_path / "data" / "soul" / "SOUL.md"
    soul.parent.mkdir(parents=True)
    soul.write_text("# SOUL\nordinary prose\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "leak.md").symlink_to(soul)
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/leak.md", max_lines=100)

    assert "ordinary prose" in out


@pytest.mark.asyncio
async def test_read_file_refuses_symlink_escaping_repo_entirely(tmp_path: Path) -> None:
    # 🔴 The one surviving symlink denial: a link under src pointing OUTSIDE the repo
    # (an absolute system path) is refused — the real path escapes the repo boundary.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "etc_link").symlink_to("/etc/hosts")
    intro = _make(tmp_path, _FakeRunner())

    with pytest.raises(DeniedPathError):
        await intro.read_file("src/etc_link", max_lines=100)


@pytest.mark.asyncio
async def test_read_file_allows_symlink_staying_within_allowed_root(
    tmp_path: Path,
) -> None:
    # The symlink defence is precise, not blanket: a link that resolves to a path
    # still INSIDE the repo reads normally (no false denial).
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "m.py").write_text("module_code = 1\n", encoding="utf-8")
    (tmp_path / "src" / "alias").symlink_to(pkg)
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/alias/m.py", max_lines=10)

    assert "module_code = 1" in out


@pytest.mark.asyncio
async def test_read_file_refuses_absolute_path_outside_repo(tmp_path: Path) -> None:
    # 🔴 US-6: an absolute path outside the repo is denied by the guard BEFORE any
    # disk touch (no symlink even involved).
    intro = _make(tmp_path, _FakeRunner())

    with pytest.raises(DeniedPathError):
        await intro.read_file("/etc/passwd", max_lines=10)


@pytest.mark.asyncio
async def test_read_file_reads_dotdot_path_resolving_within_repo(
    tmp_path: Path,
) -> None:
    # BOB-067: a ``..`` path that dips out of src but resolves back UNDER the repo
    # (config/) is now readable — containment is by resolved location, not spelling.
    (tmp_path / "src").mkdir()  # must exist so the OS can resolve ``src/..``
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "bob.yaml").write_text("timeout: 30\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.read_file("src/../config/bob.yaml", max_lines=10)

    assert "timeout" in out


@pytest.mark.asyncio
async def test_read_file_surfaces_oserror_as_honest_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An allowed, present file whose open raises a generic OSError (e.g. permissions)
    # yields an honest refusal string — never a traceback, never fabricated content.
    src = tmp_path / "src" / "locked.py"
    src.parent.mkdir(parents=True)
    src.write_text("code = 1\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    def _boom(*_args: object, **_kwargs: object) -> str:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "read_text", _boom)

    out = await intro.read_file("src/locked.py", max_lines=10)

    assert "could not read" in out.lower()


# --- list_dir (BOB-067 repo navigation) ---------------------------------------


@pytest.mark.asyncio
async def test_list_dir_lists_entries_with_kind_and_size(tmp_path: Path) -> None:
    pkg = tmp_path / "src" / "bob"
    pkg.mkdir(parents=True)
    (pkg / "app.py").write_text("x = 1\n", encoding="utf-8")
    (pkg / "sub").mkdir()
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.list_dir("src/bob")

    lines = out.splitlines()
    assert lines == ["app.py\tfile\t6", "sub/\tdir"]  # sorted; dir has no size


@pytest.mark.asyncio
async def test_list_dir_lists_beadloom_dir(tmp_path: Path) -> None:
    # 🔴 The live bug: listing .beadloom/ must return the REAL entries now.
    graph = tmp_path / ".beadloom" / "_graph"
    graph.mkdir(parents=True)
    (graph / "nodes.yml").write_text("nodes: []\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.list_dir(".beadloom")

    assert "_graph/\tdir" in out


@pytest.mark.asyncio
async def test_list_dir_empty_directory_is_honest(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.list_dir("src")

    assert "empty" in out.lower()


@pytest.mark.asyncio
async def test_list_dir_missing_path_is_honest_not_fabricated(tmp_path: Path) -> None:
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.list_dir("does/not/exist")

    assert "not a directory" in out.lower()


@pytest.mark.asyncio
async def test_list_dir_on_a_file_is_honest(tmp_path: Path) -> None:
    src = tmp_path / "src" / "app.py"
    src.parent.mkdir(parents=True)
    src.write_text("x = 1\n", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.list_dir("src/app.py")

    assert "not a directory" in out.lower()


@pytest.mark.asyncio
async def test_list_dir_refuses_escape_past_repo(tmp_path: Path) -> None:
    intro = _make(tmp_path, _FakeRunner())

    with pytest.raises(DeniedPathError):
        await intro.list_dir("../../etc")


@pytest.mark.asyncio
async def test_list_dir_sanitizes_entry_names(tmp_path: Path) -> None:
    # A secret-shaped filename is redacted on output like any other tool text.
    d = tmp_path / "src"
    d.mkdir()
    (d / "sk-abcdef0123456789secret.txt").write_text("x", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.list_dir("src")

    assert "sk-abcdef0123456789secret" not in out
    assert "REDACTED" in out


# --- find_file (BOB-067 repo navigation) --------------------------------------


@pytest.mark.asyncio
async def test_find_file_matches_by_glob_across_tree(tmp_path: Path) -> None:
    (tmp_path / "src" / "bob").mkdir(parents=True)
    (tmp_path / "src" / "bob" / "app.py").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "bob" / "cli.py").write_text("x", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "readme.md").write_text("x", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.find_file("*.py")

    assert out.splitlines() == ["src/bob/app.py", "src/bob/cli.py"]


@pytest.mark.asyncio
async def test_find_file_matches_exact_name(tmp_path: Path) -> None:
    (tmp_path / ".beadloom" / "_graph").mkdir(parents=True)
    (tmp_path / ".beadloom" / "_graph" / "nodes.yml").write_text("x", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.find_file("nodes.yml")

    assert out.splitlines() == [".beadloom/_graph/nodes.yml"]


@pytest.mark.asyncio
async def test_find_file_skips_dot_git(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    (tmp_path / "config").write_text("real", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.find_file("config")

    assert out.splitlines() == ["config"]  # the .git/config match is skipped


@pytest.mark.asyncio
async def test_find_file_empty_result_is_honest(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.find_file("*.rs")

    assert "no files" in out.lower()


@pytest.mark.asyncio
async def test_find_file_empty_pattern_is_honest(tmp_path: Path) -> None:
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.find_file("   ")

    assert "no files" in out.lower()


@pytest.mark.asyncio
async def test_find_file_caps_results_with_truncation_note(tmp_path: Path) -> None:
    d = tmp_path / "src"
    d.mkdir()
    for i in range(_FIND_FILE_MAX_RESULTS + 5):
        (d / f"m{i:04d}.py").write_text("x", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.find_file("*.py")

    content_lines = [ln for ln in out.splitlines() if ln.endswith(".py")]
    assert len(content_lines) == _FIND_FILE_MAX_RESULTS
    assert "truncated" in out.lower()


@pytest.mark.asyncio
async def test_find_file_skips_symlink_escaping_repo(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    # A symlink whose real path escapes the repo is not reported as an in-repo match.
    (tmp_path / "src" / "outside.py").symlink_to("/etc/hosts")
    (tmp_path / "src" / "real.py").write_text("x", encoding="utf-8")
    intro = _make(tmp_path, _FakeRunner())

    out = await intro.find_file("*.py")

    assert out.splitlines() == ["src/real.py"]


# --- default exec runner (real subprocess, no shell) --------------------------


@pytest.mark.asyncio
async def test_default_exec_runner_captures_stdout() -> None:
    runner = _ExecRunner()
    out = await runner(["printf", "hello-world"], timeout=5.0)

    assert "hello-world" in out


@pytest.mark.asyncio
async def test_default_exec_runner_times_out() -> None:
    runner = _ExecRunner()
    out = await runner(["sleep", "5"], timeout=0.1)

    assert "timed out" in out.lower()
