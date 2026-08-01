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
