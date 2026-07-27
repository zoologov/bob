# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Diagrams domain — pure parsing of mermaid out of Bob's reply text (BOB-037).

The reliability core of «Боб рисует»: the model UNRELIABLY calls the
``render_diagram`` tool — most of the time it just writes the mermaid as a fenced
```mermaid block in its TEXT reply, so no image is sent. This package holds the
PURE, side-effect-free helpers the application uses to fix that: find the fenced
mermaid blocks in a reply, strip them out (the rendered image replaces them), and
normalise a source for dedup against a tool-rendered diagram. It has no I/O and no
rendering — the application composes these with a
:class:`~bob.domain.ports.DiagramRenderer`.
"""

from bob.capabilities.diagrams.mermaid_blocks import (
    extract_mermaid_blocks,
    normalize_mermaid,
    strip_mermaid_blocks,
)

__all__ = [
    "extract_mermaid_blocks",
    "normalize_mermaid",
    "strip_mermaid_blocks",
]
