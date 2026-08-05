# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Shared deterministic fake :class:`RepoIntrospector` for capability tests.

The introspection capabilities (``inspect_architecture`` / ``read_code`` /
``list_work``) delegate to the :class:`~bob.domain.ports.RepoIntrospector` port.
This fake records each call and returns canned text with NO subprocess and NO
disk, so the capability tests are deterministic and never touch the real repo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.introspection.health_form import (
    HealthRequestError,
    UnknownCheckError,
)
from bob.capabilities.ports import ArchitectureDiagram, ProjectHealth

if TYPE_CHECKING:
    from bob.capabilities.introspection.graph_form import GraphFormKind


class FakeRepoIntrospector:
    """A scripted :class:`RepoIntrospector`: records calls, returns canned text."""

    def __init__(
        self,
        *,
        architecture: str = "",
        search: str = "",
        file_text: str = "",
        tasks: str = "",
        history: str = "",
        listing: str = "",
        found: str = "",
        commits: str = "",
        comments: str = "",
        task_detail: str = "",
        tasks_by_status_text: str = "",
        diagram: str = "",
        diagram_form: GraphFormKind = "overview",
        impact_text: str = "",
        health_report: str = "",
        raise_on_diagram: bool = False,
        raise_on_impact: bool = False,
        raise_on_health: bool = False,
        health_error: str = "not a read-only project-health check: simulated",
        health_error_type: type[HealthRequestError] = UnknownCheckError,
        files_by_path: dict[str, str] | None = None,
        tasks_by_query: dict[str, str] | None = None,
        raise_on_read: bool = False,
        raise_on_tasks: bool = False,
    ) -> None:
        self._architecture = architecture
        self._search = search
        self._file_text = file_text
        self._tasks = tasks
        self._history = history
        self._listing = listing
        self._found = found
        self._commits = commits
        self._comments = comments
        self._task_detail = task_detail
        self._tasks_by_status_text = tasks_by_status_text
        # BOB-091.1: the architecture-diagram + impact reads. ``diagram_form`` scripts
        # which form the port says it DREW (the honest fallback report), and the
        # ``raise_on_*`` flags model a refused (non-ref) slot without a subprocess.
        self._diagram = diagram
        self._diagram_form = diagram_form
        self._impact_text = impact_text
        self._raise_on_diagram = raise_on_diagram
        self._raise_on_impact = raise_on_impact
        # BOB-091.2: the project-health read. ``raise_on_health`` models a slot refused
        # BEFORE any subprocess, and ``health_error_type`` picks WHICH refusal — the real
        # port raises the planner's own ``UnknownCheckError`` / ``InvalidGitRefError``, and
        # the capability must feed the matching hint back to the model. 🔴 The TYPE decides,
        # not the message: before BOB-091.4 the capability sniffed the prose (Minor-7), so
        # the fake now models the types the real planner actually raises.
        self._health_report = health_report
        self._raise_on_health = raise_on_health
        self._health_error = health_error
        self._health_error_type = health_error_type
        # Per-path / per-query scripting for the code_rationale tests: a path absent
        # from ``files_by_path`` returns "" (a missing doc → skipped), so the fake can
        # model "PRD present, RFC/BRIEF absent" without disk.
        self._files_by_path = files_by_path
        self._tasks_by_query = tasks_by_query
        self._raise_on_read = raise_on_read
        self._raise_on_tasks = raise_on_tasks
        self.architecture_calls: list[str] = []
        self.search_calls: list[str] = []
        self.read_calls: list[tuple[str, int]] = []
        self.task_calls: list[str] = []
        self.history_calls: list[str] = []
        self.list_dir_calls: list[str] = []
        self.find_file_calls: list[str] = []
        self.recent_commits_calls: list[int] = []
        self.task_comments_calls: list[str] = []
        self.show_task_calls: list[str] = []
        self.tasks_by_status_calls: list[str | None] = []
        self.diagram_calls: list[tuple[str | None, int | None, str | None]] = []
        self.impact_calls: list[str] = []
        self.health_calls: list[tuple[str, str | None]] = []

    async def architecture_context(self, ref: str) -> str:
        self.architecture_calls.append(ref)
        return self._architecture

    async def search_code(self, query: str) -> str:
        self.search_calls.append(query)
        return self._search

    async def read_file(self, path: str, *, max_lines: int) -> str:
        self.read_calls.append((path, max_lines))
        if self._raise_on_read:
            raise OSError("simulated read failure")
        if self._files_by_path is not None:
            return self._files_by_path.get(path, "")
        return self._file_text

    async def list_tasks(self, query: str) -> str:
        self.task_calls.append(query)
        if self._raise_on_tasks:
            raise OSError("simulated tracker failure")
        if self._tasks_by_query is not None:
            return self._tasks_by_query.get(query, "")
        return self._tasks

    async def code_history(self, path: str) -> str:
        self.history_calls.append(path)
        return self._history

    async def list_dir(self, path: str) -> str:
        self.list_dir_calls.append(path)
        return self._listing

    async def find_file(self, pattern: str) -> str:
        self.find_file_calls.append(pattern)
        return self._found

    async def recent_commits(self, count: int) -> str:
        self.recent_commits_calls.append(count)
        return self._commits

    async def task_comments(self, bead_id: str) -> str:
        self.task_comments_calls.append(bead_id)
        return self._comments

    async def show_task(self, bead_id: str) -> str:
        self.show_task_calls.append(bead_id)
        return self._task_detail

    async def tasks_by_status(self, status: str | None) -> str:
        self.tasks_by_status_calls.append(status)
        return self._tasks_by_status_text

    async def architecture_diagram(
        self,
        ref: str | None = None,
        *,
        depth: int | None = None,
        internals_of: str | None = None,
    ) -> ArchitectureDiagram:
        self.diagram_calls.append((ref, depth, internals_of))
        if self._raise_on_diagram:
            raise ValueError("not a valid graph ref: simulated")
        requested: GraphFormKind = (
            "components" if internals_of else ("node" if ref else "overview")
        )
        return ArchitectureDiagram(
            mermaid=self._diagram, form=self._diagram_form, requested=requested
        )

    async def impact(self, ref: str) -> str:
        self.impact_calls.append(ref)
        if self._raise_on_impact:
            raise ValueError("not a valid graph ref: simulated")
        return self._impact_text

    async def project_health(
        self, check: str, *, since: str | None = None
    ) -> ProjectHealth:
        if self._raise_on_health:
            raise self._health_error_type(self._health_error)
        self.health_calls.append((check, since))
        return ProjectHealth(check=check, report=self._health_report)
