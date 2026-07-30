# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Acceptance + guardrail tests for ``code_rationale`` (BOB-038 PRD US-1..5).

The unit suite (``test_code_rationale.py``) drives the skill over a hand-written
fake port. THIS module is the missing half: it wires the skill over the REAL
:class:`SubprocessRepoIntrospector` + :class:`PrivacyGuard`, with only the
subprocess boundary faked (a recording runner) and real feature-doc files on a tmp
repo. So it proves the whole chain end-to-end:

* **US-1..3 (the rationale links)** — a path query → real ``git log`` fixed-form →
  ``parse_bead_refs`` → real ``bd`` form + real feature-doc reads + real
  ``beadloom`` graph, composed into ONE grounded "почему" that names the real bead
  and quotes the real decision docs (never a guess).
* **US-4 (honest not-found)** — a history with no ``[BOB-XXX]`` key yields
  "история … не зафиксирована" with NO tracker/doc fan-out — never fabricated.
* **🔴 US-5 (privacy invariant)** — every subprocess argv the skill issues is a
  read-only allowlisted form (``git log`` fixed forms / ``bd`` read subcommands /
  ``beadloom`` read subcommands), every file it reads is confined to the
  feature-doc subtree, and the live ``PrivacyGuard`` still denies SOUL / ``bob.db``
  / ``.env`` / ``config`` even if asked. The git allowlist refuses any non-``log``
  form at this layer too.

Deterministic: a faked runner (no real git/bd/beadloom), tmp-path feature docs (no
real repo). No network, no subprocess.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from bob.capabilities.adapters.introspection.subprocess_introspector import (
    DisallowedCommandError,
    SubprocessRepoIntrospector,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard
from bob.capabilities.usecases.code_rationale import make_code_rationale_capability

_FEATURE_DOCS_BASE = ".claude/development/docs/features"

# The read-only subcommands each binary is allowed to run, mirrored from the adapter
# allowlist so the guardrail assertions are explicit (not coupled to the prod tuple).
_ALLOWED_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "git": frozenset({"log"}),
    "bd": frozenset({"ready", "show", "list"}),
    "beadloom": frozenset({"ctx", "graph", "why", "search"}),
}

# Personal / denied roots the skill must NEVER request (US-5 invariant).
_DENIED_PATHS = (
    "data/soul/SOUL.md",
    "data/bob.db",
    ".env",
    "config/settings.toml",
)


class _RecordingRunner:
    """A faked subprocess boundary: records every argv, returns canned text — ARGV-AWARE.

    The canned stdout is keyed on the most specific match first: a
    ``"<binary> <subcommand>"`` key (e.g. ``"bd list"`` vs ``"bd show"``) wins over a
    bare ``"<binary>"`` key (e.g. ``"git"`` / ``"beadloom"``). This distinction is
    load-bearing for the regression guard: a fake keyed only on the binary cannot tell
    an UNFILTERED ``bd list`` backlog dump apart from a targeted ``bd show <id>``, which
    is exactly how the original pollution bug slipped past the suite. Keying on argv
    lets a test inject a distinct ``bd list`` backlog and assert it never leaks.
    """

    def __init__(self, by_binary: dict[str, str]) -> None:
        self.calls: list[list[str]] = []
        self._by_binary = by_binary

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        self.calls.append(list(argv))
        if len(argv) >= 2:
            specific = self._by_binary.get(f"{argv[0]} {argv[1]}")
            if specific is not None:
                return specific
        return self._by_binary.get(argv[0], "")


class _RecordingIntrospector(SubprocessRepoIntrospector):
    """Real introspector that ALSO records every ``read_file`` path it is asked for.

    The base adapter does not expose the read requests; recording them lets the
    privacy test assert the skill never even *requests* a denied path (the guard
    would deny it anyway, but "never asked" is the stronger, fabrication-proof claim).
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.read_paths: list[str] = []

    async def read_file(self, path: str, *, max_lines: int) -> str:
        self.read_paths.append(path)
        return await super().read_file(path, max_lines=max_lines)


def _make_introspector(
    tmp_path: Path, runner: _RecordingRunner
) -> _RecordingIntrospector:
    return _RecordingIntrospector(
        PrivacyGuard(tmp_path),
        runner=runner,
        beadloom_bin="beadloom",
        bd_bin="bd",
        git_bin="git",
    )


def _write_feature_doc(tmp_path: Path, key: str, doc: str, text: str) -> None:
    """Create a real ``.claude/development/docs/features/<key>/<doc>`` under tmp."""
    target = tmp_path / _FEATURE_DOCS_BASE / key / doc
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


# --- US-1..3: the grounded rationale links code → bead → docs → graph ----------


async def test_rationale_is_grounded_in_real_git_bd_docs_and_graph(
    tmp_path: Path,
) -> None:
    # A real feature doc (PRD + RFC) for the decision the history points at.
    _write_feature_doc(
        tmp_path, "BOB-025", "PRD.md", "PRD: адресность через conversational floor"
    )
    _write_feature_doc(
        tmp_path, "BOB-025", "RFC.md", "RFC: floor выбирает получателя по истории"
    )
    runner = _RecordingRunner(
        {
            "git": "abc123 [BOB-025] адресность через floor\ndef456 chore: tidy",
            "bd": "bob-xyz [BOB-025] решение: conversational floor",
            "beadloom": "domain bob → application.addressing",
        }
    )
    introspector = _make_introspector(tmp_path, runner)
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/application/conversation.py"})

    assert isinstance(result, Mapping)
    rationale = str(result["rationale"])
    # code → bead (US-1): the real decision key surfaced from git history.
    assert "BOB-025" in rationale
    # bead → doc (US-2/3): the real PRD and RFC "why" text is woven in.
    assert "conversational floor" in rationale
    assert "floor выбирает получателя" in rationale
    # code → graph (US-3): the structural picture is woven in.
    assert "application.addressing" in rationale
    # Grounded, not guessed: no bead key the history never mentioned is fabricated.
    assert "BOB-999" not in rationale


async def test_rationale_only_issues_readonly_allowlisted_argv(
    tmp_path: Path,
) -> None:
    # US-5: every subprocess the skill drives is a read-only allowlisted form — a
    # path history (git log fixed form), a bd read subcommand, a beadloom read.
    _write_feature_doc(tmp_path, "BOB-025", "PRD.md", "why")
    runner = _RecordingRunner(
        {
            "git": "abc123 [BOB-025] decision",
            "bd": "tracker text",
            "beadloom": "graph text",
        }
    )
    introspector = _make_introspector(tmp_path, runner)
    cap = make_code_rationale_capability(introspector)

    await cap.execute({"query": "src/bob/app.py"})

    assert runner.calls, "the skill must have grounded against the tools"
    for argv in runner.calls:
        binary, subcommand = argv[0], argv[1]
        assert binary in _ALLOWED_SUBCOMMANDS, f"unexpected binary: {binary}"
        assert subcommand in _ALLOWED_SUBCOMMANDS[binary], f"non-readonly: {argv}"
        # git is ONLY ever ``git log`` in a fixed form (never show/diff/blame).
        if binary == "git":
            assert subcommand == "log"
    # The git history call used the bounded ``--oneline -n <N> -- <path>`` form.
    git_calls = [a for a in runner.calls if a[0] == "git"]
    assert git_calls
    for git_argv in git_calls:
        assert "--oneline" in git_argv
        # The dynamic path slot stays inside the repo (after the ``--`` separator).
        assert git_argv[-2] == "--"
        assert not git_argv[-1].startswith("-")


# --- regression: an unfiltered ``bd list`` backlog must NEVER pollute the rationale --


async def test_rationale_does_not_inject_an_unfiltered_bd_list_backlog(
    tmp_path: Path,
) -> None:
    # Regression for BOB-038 review .4: a ``[BOB-025]`` human key is NOT a bd hash-id,
    # so the old per-key ``list_tasks(key)`` fell through to an UNFILTERED ``bd list``
    # and injected that key-agnostic backlog dump under every header (up to 5x). The
    # fix drops the tracker source from this path — the feature doc is the "why".
    _write_feature_doc(
        tmp_path, "BOB-025", "PRD.md", "PRD: адресность через conversational floor"
    )
    # A distinct backlog blob the argv-aware fake returns ONLY for ``bd list`` — its
    # presence in the rationale would prove the pollution regressed.
    backlog = "BACKLOG-DUMP bob-aaa open / bob-bbb open / bob-ccc closed (unrelated)"
    runner = _RecordingRunner(
        {
            "git": "abc123 [BOB-025] адресность через floor\ndef456 chore: tidy",
            "bd list": backlog,
            "bd show": "bob-xyz show output",
            "beadloom": "domain bob → application.addressing",
        }
    )
    introspector = _make_introspector(tmp_path, runner)
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/application/conversation.py"})

    assert isinstance(result, Mapping)
    rationale = str(result["rationale"])
    # The key + the feature-doc "why" are present (the clean rationale) ...
    assert "BOB-025" in rationale
    assert "conversational floor" in rationale
    # ... and the unfiltered backlog dump is NOT — the regression guard.
    assert "BACKLOG-DUMP" not in rationale
    assert backlog not in rationale
    # Strongest form: the skill never queries the tracker per key at all (no bd call),
    # so the pollution source cannot be reached.
    assert all(argv[0] != "bd" for argv in runner.calls)


# --- US-4: honest "not recorded" through the real introspector -----------------


async def test_history_without_a_bead_key_is_honestly_not_recorded(
    tmp_path: Path,
) -> None:
    # Real git log returns commits, but NONE carries a [BOB-XXX] decision key.
    runner = _RecordingRunner({"git": "abc123 tidy up\ndef456 wip refactor"})
    introspector = _make_introspector(tmp_path, runner)
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/app.py"})

    assert isinstance(result, Mapping)
    assert "не зафиксирован" in str(result["rationale"]).lower()
    # No keys → no tracker fan-out, no doc reads (it does not fabricate a trail).
    assert all(argv[0] != "bd" for argv in runner.calls)
    assert introspector.read_paths == []


# --- 🔴 US-5: the privacy invariant, end to end --------------------------------


async def test_skill_only_reads_feature_doc_paths_via_the_real_guard(
    tmp_path: Path,
) -> None:
    _write_feature_doc(tmp_path, "BOB-034", "PRD.md", "read-scope rationale")
    runner = _RecordingRunner(
        {"git": "abc [BOB-034] read-scope\ndef [BOB-017] introspection seam"}
    )
    introspector = _make_introspector(tmp_path, runner)
    cap = make_code_rationale_capability(introspector)

    await cap.execute({"query": "src/bob/app.py"})

    assert introspector.read_paths, "the skill should have read at least one doc"
    for path in introspector.read_paths:
        # Confined to the feature-doc subtree (an allowed read-only root) ...
        assert path.startswith(_FEATURE_DOCS_BASE + "/")
        # ... and only the three "why" doc shapes — never an arbitrary file.
        assert path.rsplit("/", 1)[-1] in {"PRD.md", "RFC.md", "BRIEF.md"}
    # No denied personal path was ever even requested (in a read OR an argv token).
    all_argv_tokens = [token for argv in runner.calls for token in argv]
    for denied in _DENIED_PATHS:
        assert all(denied not in p for p in introspector.read_paths)
        assert all(denied not in token for token in all_argv_tokens)


@pytest.mark.parametrize("denied", _DENIED_PATHS)
def test_live_guard_allows_in_repo_paths_but_skill_confines_itself(
    tmp_path: Path, denied: str
) -> None:
    # BOB-067: the guard now allows ANY in-repo path (full-repo access) — SOUL /
    # bob.db / .env / config included; secret VALUES are handled by ``sanitize`` on
    # output. The code_rationale skill nonetheless never reaches them: its confinement
    # is by its own PRD/RFC/BRIEF doc-shape selection (asserted above), not the guard.
    guard = PrivacyGuard(tmp_path)

    assert guard.allows_path(Path(denied)) is True
    assert guard.allows_path(Path(f"{_FEATURE_DOCS_BASE}/BOB-025/PRD.md")) is True
    # The one thing the guard still forbids is an escape past the repo boundary.
    assert guard.allows_path(Path("../../etc/passwd")) is False


async def test_introspector_refuses_a_non_log_git_form_at_this_layer(
    tmp_path: Path,
) -> None:
    # Re-confirm at the adapter layer the skill sits on: git is ONLY ``git log`` in a
    # fixed form. Any other subcommand is refused before a process is spawned.
    runner = _RecordingRunner({})
    introspector = _make_introspector(tmp_path, runner)

    for bad in ("show", "diff", "blame", "cat-file"):
        with pytest.raises(DisallowedCommandError):
            await introspector._run("git", bad, "--oneline")
    assert runner.calls == []
