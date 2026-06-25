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
