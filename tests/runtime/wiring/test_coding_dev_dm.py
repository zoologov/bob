# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``_build_dm_live_streamer`` — the dev-channel live-stream wiring switch (BOB-082.3).

The DM live-stream renderer ships inert behind the ``coder.dev_dm`` flag (default off,
mirroring ``coder.nl_autostart``). This builder is the ONE place the flag is read: off →
``None`` so the run is narrated to the group capped exactly as before; on → a
:class:`_DmLiveStreamer` targeting the owner's private DM (default ``owner_id``, or the
explicit ``coder.dev_dm_chat_id``), with no topic thread (a 1:1 chat).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bob.coding.adapters.live_stream import _DmLiveStreamer
from bob.coding.adapters.owner_notifier import _CodingOwnerNotifier
from bob.runtime.wiring.coding import _build_dm_live_streamer

if TYPE_CHECKING:
    from bob.infrastructure.telegram.gateway import BotLike

_OWNER_ID = 27468732


class _StubBot:
    """A bot placeholder — the streamer is assembled, never sent through, during wiring."""


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def test_flag_off_yields_no_streamer() -> None:
    assert _build_dm_live_streamer({}, bot=_bot(), owner_id=_OWNER_ID) is None


def test_flag_off_explicit_false_yields_no_streamer() -> None:
    coder = {"dev_dm": False}
    assert _build_dm_live_streamer(coder, bot=_bot(), owner_id=_OWNER_ID) is None


def test_flag_on_builds_the_streamer() -> None:
    coder = {"dev_dm": True}
    streamer = _build_dm_live_streamer(coder, bot=_bot(), owner_id=_OWNER_ID)
    assert isinstance(streamer, _DmLiveStreamer)


def test_flag_on_targets_the_owner_dm_by_default() -> None:
    coder = {"dev_dm": True}
    streamer = _build_dm_live_streamer(coder, bot=_bot(), owner_id=_OWNER_ID)
    assert isinstance(streamer, _DmLiveStreamer)
    notifier = streamer._notifier
    # The DM notifier targets the owner's own chat (a 1:1 DM), with no topic thread.
    assert isinstance(notifier, _CodingOwnerNotifier)
    assert notifier._chat_id == _OWNER_ID
    assert notifier._topic_id is None


def test_flag_on_honours_explicit_dev_dm_chat_id() -> None:
    coder = {"dev_dm": True, "dev_dm_chat_id": 99}
    streamer = _build_dm_live_streamer(coder, bot=_bot(), owner_id=_OWNER_ID)
    assert isinstance(streamer, _DmLiveStreamer)
    notifier = streamer._notifier
    assert isinstance(notifier, _CodingOwnerNotifier)
    assert notifier._chat_id == 99
