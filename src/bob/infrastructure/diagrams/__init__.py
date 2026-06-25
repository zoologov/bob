# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Local diagram rendering adapters (BOB-035).

Realises the :class:`~bob.domain.ports.DiagramRenderer` port LOCALLY — mermaid
source never leaves the machine. The first adapter shells the local mermaid-cli
(``mmdc``) via ``create_subprocess_exec`` (never a shell).
"""

from bob.infrastructure.diagrams.mmdc_renderer import (
    DiagramRenderError,
    SubprocessMmdcRenderer,
)

__all__ = ["DiagramRenderError", "SubprocessMmdcRenderer"]
