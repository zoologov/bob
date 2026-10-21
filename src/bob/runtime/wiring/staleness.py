# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root staleness wiring — «врезка перед отправкой» behind ``presence.staleness``.

The staleness consumption seam (BOB-066 Срез W.3): this is the ONE place the
``presence.staleness`` flag is read and the
:class:`~bob.application.runtime.staleness_reassessor.StalenessReassessor` is assembled over the
Tier-0 :class:`~bob.presence.adapters.staleness_judge.LlmStalenessJudge` and the pure
:class:`~bob.presence.staleness.StalenessGate`. Off (the default — the whole «человеческое
групповое присутствие» epic ships as one piece) the reassessor is ``None`` so ``HandleMessage``
sends every drafted reply unchanged and Bob is byte-identical.

The flag follows the nested ``<section>.enabled`` convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.runtime.staleness_reassessor import StalenessReassessor
from bob.presence.adapters.staleness_judge import LlmStalenessJudge
from bob.presence.staleness import StalenessGate
from bob.runtime.config import _flag, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.application.router.llm_router import LLMRouter


def staleness_enabled(config: Mapping[str, object]) -> bool:
    """Return whether the staleness врезка is on (``presence.staleness.enabled``, off default).

    Read in the composition root so BOTH the reassessor (``HandleMessage``) and the intake
    dispatcher's turn-local ``peek_arrivals`` binding gate on ONE flag — off → the peek is never
    bound and the reply path is byte-identical.
    """
    return _flag(_section(_section(config, "presence"), "staleness"), "enabled")


def build_staleness_reassessor(
    config: Mapping[str, object], *, router: LLMRouter
) -> StalenessReassessor | None:
    """Assemble the staleness reassessor, or ``None`` when ``presence.staleness`` is off.

    Off (the default) → ``None`` so ``HandleMessage`` sends every draft unchanged (byte-identical).
    On → the app collaborator over the Tier-0 :class:`LlmStalenessJudge` + the pure
    :class:`StalenessGate`, so just before sending Bob rereads what landed during generation.
    """
    if not staleness_enabled(config):
        return None
    return StalenessReassessor(LlmStalenessJudge(router=router), StalenessGate())
