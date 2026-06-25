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
    ) -> None:
        self._architecture = architecture
        self._search = search
        self._file_text = file_text
        self._tasks = tasks
        self._history = history
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
        return self._file_text

    async def list_tasks(self, query: str) -> str:
        self.task_calls.append(query)
        return self._tasks

    async def code_history(self, path: str) -> str:
        self.history_calls.append(path)
        return self._history
