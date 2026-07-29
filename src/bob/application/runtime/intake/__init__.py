# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app

"""Intake-развязка (BOB-066 Срез 2.1) — the concurrency seam between the poller and Bob.

The Telegram poller used to ``await`` the whole reply generation inside its loop, so the
next ``get_updates`` never fired while Bob was thinking. This package decouples the two:
the bus subscriber becomes the fast, non-blocking :class:`ChatDispatcher.submit` (normalise
→ buffer → return); a per-``chat_id`` worker then drains the buffer and runs the real
:class:`~bob.application.usecases.handle_message.HandleMessage` sequentially.

Three cohesive pieces:

* :mod:`.decisions` — the PURE debounce/scope decision core (quiet-window flush + per-turn
  rng-seed derivation); deterministic, mutation-tested.
* :mod:`.scope` — :class:`TurnScope`: the isolated per-turn context (rng seeded from
  ``base_seed``/``chat_id``/``message_id`` so turn-local draws never leak — INV-4).
* :mod:`.inbox` / :mod:`.dispatcher` — the async :class:`ChatInbox` buffer+debounce and the
  :class:`ChatDispatcher` per-chat workers that serialize a chat's messages (INV-5) while
  running different chats in parallel — with a focused message flushed at once (INV-1/10).
"""

from __future__ import annotations

from bob.application.runtime.intake.dispatcher import ChatDispatcher
from bob.application.runtime.intake.focus import make_focus_predicate
from bob.application.runtime.intake.inbox import ChatInbox
from bob.application.runtime.intake.scope import TurnScope, new_turn_scope

__all__ = [
    "ChatDispatcher",
    "ChatInbox",
    "TurnScope",
    "make_focus_predicate",
    "new_turn_scope",
]
