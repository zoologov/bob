# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``code_rationale`` — the code↔decision "why" skill (BOB-038 .2).

The orchestrating capability that ties a piece of code to the decisions behind it:
``code_history`` → ``parse_bead_refs`` → per-key bracketing commit line(s)
(``commits_mentioning``) + feature-doc reads (PRD/RFC/BRIEF) +
``architecture_context`` (graph), composed into one compact "почему". The tracker
(``bd``) is deliberately NOT queried per key — a ``[BOB-NNN]`` human key cannot
resolve to a ``bd show`` and the listing fallback would pollute the rationale with an
unfiltered backlog dump. It is honest — an empty bead trail yields "история … не
зафиксирована", never a fabricated rationale — and resilient: a missing doc or a
failing source is skipped, not crashed. The bead-ref fan-out is bounded. It only ever
reads feature-doc paths (privacy). Deterministic on a fake port — no subprocess.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from bob.application.capabilities.code_rationale import (
    make_code_rationale_capability,
)

from .fakes import FakeRepoIntrospector

_FEATURE_DOCS_BASE = ".claude/development/docs/features"


def test_capability_advertises_the_code_rationale_contract() -> None:
    cap = make_code_rationale_capability(FakeRepoIntrospector())

    assert cap.name == "code_rationale"
    assert cap.description
    assert cap.permission == "safe"
    schema = cap.input_schema
    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert properties["query"] == {"type": "string"}
    assert schema["required"] == ["query"]


async def test_execute_links_code_to_bead_doc_and_graph() -> None:
    introspector = FakeRepoIntrospector(
        history="abc123 [BOB-037] Схемы: авто-рендер inline-mermaid",
        files_by_path={
            f"{_FEATURE_DOCS_BASE}/BOB-037/PRD.md": "PRD: Боб умеет рисовать схемы",
        },
        architecture="domain bob → infrastructure.diagrams",
    )
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/application/capabilities/render_diagram.py"})

    assert isinstance(result, Mapping)
    rationale = str(result["rationale"])
    # code → bead (US-1): the decision key is surfaced.
    assert "BOB-037" in rationale
    # bead → commit (US-2): the bracketing commit subject is woven in (not bd).
    assert "авто-рендер inline-mermaid" in rationale
    # bead → doc (US-2/3): the feature-doc "why" is woven in.
    assert "Боб умеет рисовать схемы" in rationale
    # code → graph (US-3): the structural picture is woven in.
    assert "infrastructure.diagrams" in rationale
    # The tracker (bd) is never queried per key — the docs + commits are the "why".
    assert introspector.task_calls == []
    # The orchestration delegated to the port with the original query.
    assert introspector.history_calls == [
        "src/bob/application/capabilities/render_diagram.py"
    ]
    assert introspector.architecture_calls == [
        "src/bob/application/capabilities/render_diagram.py"
    ]


async def test_execute_with_no_bead_refs_is_honest_not_recorded() -> None:
    # code_history yields commits but NONE carry a [BOB-XXX] decision key.
    introspector = FakeRepoIntrospector(
        history="abc123 tidy up\ndef456 wip",
        architecture="domain bob",
    )
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/app.py"})

    assert isinstance(result, Mapping)
    rationale = str(result["rationale"]).lower()
    assert "не зафиксирован" in rationale
    # No keys → no per-key fan-out (it does not fabricate a decision trail).
    assert introspector.task_calls == []
    assert introspector.read_calls == []


async def test_execute_skips_a_missing_feature_doc_gracefully() -> None:
    # Only PRD.md exists for the key; RFC.md / BRIEF.md are absent (return "").
    introspector = FakeRepoIntrospector(
        history="abc123 [BOB-036] фраза-тик",
        tasks_by_query={"BOB-036": "BOB-036: anti-repeat decision"},
        files_by_path={
            f"{_FEATURE_DOCS_BASE}/BOB-036/PRD.md": "PRD: ловим закрывашки",
        },
    )
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "BOB-036"})

    assert isinstance(result, Mapping)
    rationale = str(result["rationale"])
    assert "ловим закрывашки" in rationale  # present doc surfaced
    # All three doc shapes were attempted, but the missing ones did not crash.
    read_paths = [path for path, _ in introspector.read_calls]
    assert f"{_FEATURE_DOCS_BASE}/BOB-036/PRD.md" in read_paths


async def test_execute_is_resilient_to_failing_sources() -> None:
    # The tracker and every doc read blow up; the skill must still compose (graph
    # only) rather than crash the turn.
    introspector = FakeRepoIntrospector(
        history="abc123 [BOB-035] render_diagram",
        architecture="domain bob → infrastructure.diagrams",
        raise_on_read=True,
        raise_on_tasks=True,
    )
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/app.py"})

    assert isinstance(result, Mapping)
    rationale = str(result["rationale"])
    assert "infrastructure.diagrams" in rationale
    assert "BOB-035" in rationale


async def test_execute_bounds_the_bead_ref_fan_out() -> None:
    # 50 distinct decision keys in the history must NOT trigger 50 tracker shows /
    # 150 doc reads — the fan-out is capped to the top-N most-recent.
    many = "\n".join(f"sha{i} [BOB-{i:03d}] commit {i}" for i in range(50))
    introspector = FakeRepoIntrospector(history=many, architecture="domain bob")
    cap = make_code_rationale_capability(introspector)

    await cap.execute({"query": "src/bob/app.py"})

    # The fan-out is capped to the top-5 keys; each reads at most 3 docs
    # (PRD/RFC/BRIEF), so reads stay bounded too — never 50 keys x 3.
    assert 0 < len(introspector.read_calls) <= 5 * 3
    # The tracker is still never consulted, no matter how long the history.
    assert introspector.task_calls == []


async def test_execute_only_reads_feature_doc_paths() -> None:
    # Privacy: the skill must NEVER request SOUL / bob.db / .env / config — only the
    # feature-doc directory derived from the bead key.
    introspector = FakeRepoIntrospector(
        history="abc123 [BOB-034] read-scope\ndef456 [BOB-017] introspection",
        files_by_path={f"{_FEATURE_DOCS_BASE}/BOB-034/PRD.md": "why"},
    )
    cap = make_code_rationale_capability(introspector)

    await cap.execute({"query": "src/bob/app.py"})

    for path, _ in introspector.read_calls:
        assert path.startswith(_FEATURE_DOCS_BASE + "/")
        assert path.rsplit("/", 1)[-1] in {"PRD.md", "RFC.md", "BRIEF.md"}


async def test_execute_truncates_long_sources_for_a_compact_answer() -> None:
    # A very long feature-doc "why" must be trimmed (ellipsis) so the model is not
    # flooded — each per-source render carries a compact char budget.
    introspector = FakeRepoIntrospector(
        history="abc123 [BOB-038] arch context",
        files_by_path={f"{_FEATURE_DOCS_BASE}/BOB-038/PRD.md": "X" * 5000},
    )
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/app.py"})

    assert isinstance(result, Mapping)
    rationale = str(result["rationale"])
    assert "…" in rationale
    assert len(rationale) < 5000


async def test_execute_is_honest_when_history_itself_fails() -> None:
    # code_history blowing up degrades to the honest "not recorded", never a crash.
    class _Boom(FakeRepoIntrospector):
        async def code_history(self, path: str) -> str:
            self.history_calls.append(path)
            raise OSError("git unavailable")

    introspector = _Boom()
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/app.py"})

    assert isinstance(result, Mapping)
    assert "не зафиксирован" in str(result["rationale"]).lower()


async def test_execute_is_resilient_to_a_failing_graph_source() -> None:
    # The architecture (graph) source blows up; the skill must still return the bead
    # trail (decision + docs) rather than crash the turn — the graph is just omitted.
    class _ArchBoom(FakeRepoIntrospector):
        async def architecture_context(self, ref: str) -> str:
            self.architecture_calls.append(ref)
            raise OSError("beadloom unavailable")

    introspector = _ArchBoom(
        history="abc123 [BOB-038] решение про граф",
        files_by_path={f"{_FEATURE_DOCS_BASE}/BOB-038/PRD.md": "PRD: граф решений"},
    )
    cap = make_code_rationale_capability(introspector)

    result = await cap.execute({"query": "src/bob/app.py"})

    assert isinstance(result, Mapping)
    rationale = str(result["rationale"])
    assert "BOB-038" in rationale
    # The bead trail (commit subject + feature doc) survives a dead graph source.
    assert "решение про граф" in rationale
    assert "граф решений" in rationale
    # The graph source was attempted (and swallowed), no crash.
    assert introspector.architecture_calls == ["src/bob/app.py"]


async def test_execute_requires_a_string_query() -> None:
    cap = make_code_rationale_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({"query": 123})


async def test_execute_with_missing_query_key_raises() -> None:
    cap = make_code_rationale_capability(FakeRepoIntrospector())

    with pytest.raises(ValueError, match="query"):
        await cap.execute({})
