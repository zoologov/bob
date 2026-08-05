# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""Capability seam — the registry GUPPI uses to advertise and execute skills."""

from __future__ import annotations

from bob.capabilities.usecases.architecture_impact import (
    make_architecture_impact_capability,
)
from bob.capabilities.usecases.code_rationale import (
    make_code_rationale_capability,
)
from bob.capabilities.usecases.draw_architecture import (
    make_draw_architecture_capability,
)
from bob.capabilities.usecases.find_file import make_find_file_capability
from bob.capabilities.usecases.inspect_architecture import (
    make_inspect_architecture_capability,
)
from bob.capabilities.usecases.list_dir import make_list_dir_capability
from bob.capabilities.usecases.list_tasks import make_list_tasks_capability
from bob.capabilities.usecases.list_work import make_list_work_capability
from bob.capabilities.usecases.read_code import make_read_code_capability
from bob.capabilities.usecases.read_url import make_read_url_capability
from bob.capabilities.usecases.recall_memory import make_recall_memory_capability
from bob.capabilities.usecases.recent_commits import make_recent_commits_capability
from bob.capabilities.usecases.registry import (
    CapabilityNotAllowedError,
    CapabilityRegistry,
    SafeCapabilityDispatcher,
    UnknownCapabilityError,
)
from bob.capabilities.usecases.render_diagram import (
    CollectingDiagramSink,
    make_render_diagram_capability,
)
from bob.capabilities.usecases.search_memory import make_search_memory_capability
from bob.capabilities.usecases.show_task import make_show_task_capability
from bob.capabilities.usecases.task_comments import make_task_comments_capability
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.capabilities.usecases.web_search import make_web_search_capability

__all__ = [
    "CapabilityNotAllowedError",
    "CapabilityRegistry",
    "CollectingDiagramSink",
    "SafeCapabilityDispatcher",
    "ToolLoop",
    "UnknownCapabilityError",
    "make_architecture_impact_capability",
    "make_code_rationale_capability",
    "make_draw_architecture_capability",
    "make_find_file_capability",
    "make_inspect_architecture_capability",
    "make_list_dir_capability",
    "make_list_tasks_capability",
    "make_list_work_capability",
    "make_read_code_capability",
    "make_read_url_capability",
    "make_recall_memory_capability",
    "make_recent_commits_capability",
    "make_render_diagram_capability",
    "make_search_memory_capability",
    "make_show_task_capability",
    "make_task_comments_capability",
    "make_web_search_capability",
]
