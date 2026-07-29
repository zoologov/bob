# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""Pure intake decision core (BOB-066 Срез 2.1) — debounce timing + turn-seed derivation.

Deterministic, side-effect-free helpers the async :class:`~bob.application.runtime.intake.
inbox.ChatInbox` and :class:`~bob.application.runtime.intake.scope.TurnScope` are built on.
Keeping them pure makes the burst/focus behaviour exhaustively truth-tabled and mutation-
tested, while the asyncio orchestration stays a thin shell over these decisions.
"""

from __future__ import annotations


def should_debounce(*, closing: bool, has_focus: bool) -> bool:
    """Whether the inbox should still wait a quiet window before flushing the buffer.

    Two short-circuits collapse the wait to zero:

    * ``has_focus`` — 🔴 INV-1/10: a message that directly addresses Bob (mention /
      reply-to-Bob / «Боб, …») is answered at once, never held back by the debounce so a
      focus signal can never be dropped or collapsed by batching.
    * ``closing`` — a graceful drain flushes whatever is buffered immediately, so
      shutdown never blocks on a quiet window that will never come.
    """
    return not closing and not has_focus


def batch_grew(*, before: int, after: int) -> bool:
    """Whether new messages landed during the quiet window (so keep waiting for the burst).

    ``before`` is the buffer size when the window opened, ``after`` its size when the window
    elapsed: a strict increase means someone is still typing, so the debounce loops; an
    unchanged count means the burst settled and the batch flushes.
    """
    return after > before


def derive_turn_seed(*, base_seed: int, chat_id: int, message_id: int) -> str:
    """Derive a per-turn rng seed from the base seed + chat + message coordinates.

    🔴 INV-4: two messages of the same chat (different ``message_id``) and the same message
    across chats (different ``chat_id``) each seed an independent rng, so turn-local draws
    never leak between messages/turns and are reproducible regardless of dispatch timing.
    The mapping is a stable, collision-free string of the three integer coordinates.
    """
    return f"{base_seed}:{chat_id}:{message_id}"
