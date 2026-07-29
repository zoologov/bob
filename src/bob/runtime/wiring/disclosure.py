# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root disclosure wiring — «такт разглашения» behind ``presence.tact``.

The tactful-withhold consumption seam (BOB-066 Срез W.4): this is the ONE place the
``presence.tact`` flag is read and the
:class:`~bob.application.usecases.disclosure_guard.DisclosureGuard` is assembled over the
same safe-default-guarded Tier-0 :class:`~bob.social.adapters.privilege_judge.LlmPrivilegeJudge`
the permission flow uses. Off (the default — the whole «человеческое групповое присутствие»
epic ships as one piece) the guard is ``None`` so ``HandleMessage`` folds no withhold line and
Bob is byte-identical.

The flag follows the nested ``<section>.enabled`` convention. 🔴 The privilege GATE is
unchanged — this seam only swaps the dry stranger-wall for a warm refusal VOICE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.usecases.disclosure_guard import DisclosureGuard
from bob.runtime.config import _flag, _section
from bob.social.adapters.permission_channels import _SafeDefaultPrivilegeJudge
from bob.social.adapters.privilege_judge import LlmPrivilegeJudge

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.application.router import LLMRouter


def build_disclosure_guard(
    config: Mapping[str, object],
    *,
    router: LLMRouter,
    capability_hints: Sequence[str] = (),
) -> DisclosureGuard | None:
    """Assemble the disclosure guard, or ``None`` when ``presence.tact`` is off.

    Off (the default) → ``None`` so ``HandleMessage`` composes a guest turn exactly as
    before (byte-identical). On → the :class:`DisclosureGuard` over the safe-default-guarded
    Tier-0 :class:`LlmPrivilegeJudge`, so a guest ``owner_data`` request gets the warm
    :func:`~bob.personality.voice.tactful_withhold_directive` instead of the dry
    stranger-wall (the privilege gate itself is unchanged).
    """
    if not _flag(_section(_section(config, "presence"), "tact"), "enabled"):
        return None
    return DisclosureGuard(
        judge=_SafeDefaultPrivilegeJudge(LlmPrivilegeJudge(router=router)),
        capability_hints=capability_hints,
    )
