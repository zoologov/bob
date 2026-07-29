# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root rhythm wiring — the presence rhythm layer behind ``presence.rhythm``.

The presence rhythm mechanisms (share-of-voice ceiling + natural-delay floor) ship inert:
this is the ONE place the ``presence.rhythm`` flag is read and their application
collaborators are assembled and handed to the hot path. Off (the default — the whole
«человеческое групповое присутствие» epic ships as one piece) every consumption seam is
``None`` and Bob is byte-identical. On, it builds:

* the durable :class:`~bob.presence.adapters.EpisodicOutgoingActivityStore` over the shared
  connection (Bob's rolling share-of-voice window, fed by the episodic log the reply path
  already writes),
* one :class:`~bob.application.runtime.share_of_voice_gate.ShareOfVoiceGate` over that store +
  the pure :class:`~bob.presence.share_of_voice.ShareOfVoicePolicy` — handed to BOTH the
  reactive ambient-barge ceiling AND the proactive throttle, so they damp each other over one
  per-chat window (RFC Пласт 3: проактив видит только что отправленную реплику и тормозит),
* the :class:`~bob.application.runtime.delayed_turn.DelayedTurn` coordinator over the pure
  :class:`~bob.presence.natural_delay.NaturalDelayPolicy` (INV-9 human floor), with the real
  ``asyncio.sleep`` + ``time.monotonic`` injected.

All tunables live under ``presence.rhythm.*`` and default to the gentle
:class:`~bob.presence.rhythm_config.RhythmConfig` defaults.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.application.runtime.delayed_turn import DelayedTurn
from bob.application.runtime.share_of_voice_gate import ShareOfVoiceGate
from bob.presence.adapters import EpisodicOutgoingActivityStore
from bob.presence.natural_delay import NaturalDelayPolicy
from bob.presence.rhythm_config import RhythmConfig
from bob.presence.share_of_voice import ShareOfVoicePolicy
from bob.runtime.config import _flag, _float_or, _int, _section

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.presence.adapters.outgoing_activity_store import _ConnectionProvider

# The default rolling window (message-episodes) the share-of-voice store reads over — kept in
# sync with the adapter default; tunable via ``presence.rhythm.window_size``.
_DEFAULT_WINDOW_SIZE = 20


@dataclass(frozen=True, slots=True)
class RhythmWiring:
    """The presence rhythm consumption seams for the hot path (all ``None`` when off).

    ``barge_ceiling`` and ``share_ceiling`` are the SAME gate instance — the reactive
    ambient-barge ceiling and the proactive throttle share one per-chat window on purpose.
    """

    barge_ceiling: ShareOfVoiceGate | None = None
    reply_delay: DelayedTurn | None = None
    share_ceiling: ShareOfVoiceGate | None = None


def _rhythm_config(section: Mapping[str, object]) -> RhythmConfig:
    """Build the :class:`RhythmConfig` from ``presence.rhythm.*`` (defaults to the gentle base)."""
    base = RhythmConfig()
    return RhythmConfig(
        share_min_multiplier=_float_or(
            section, "share_min_multiplier", base.share_min_multiplier
        ),
        share_steepness=_float_or(section, "share_steepness", base.share_steepness),
        delay_base_seconds=_float_or(
            section, "delay_base_seconds", base.delay_base_seconds
        ),
        delay_seconds_per_char=_float_or(
            section, "delay_seconds_per_char", base.delay_seconds_per_char
        ),
        delay_complexity_seconds=_float_or(
            section, "delay_complexity_seconds", base.delay_complexity_seconds
        ),
        delay_max_seconds=_float_or(
            section, "delay_max_seconds", base.delay_max_seconds
        ),
        delay_urgency_relief=_float_or(
            section, "delay_urgency_relief", base.delay_urgency_relief
        ),
        reaction_min_gap_seconds=_float_or(
            section, "reaction_min_gap_seconds", base.reaction_min_gap_seconds
        ),
        reaction_quality_threshold=_float_or(
            section, "reaction_quality_threshold", base.reaction_quality_threshold
        ),
    )


def build_rhythm_wiring(
    config: Mapping[str, object], *, activity_provider: _ConnectionProvider
) -> RhythmWiring:
    """Assemble the presence rhythm consumption seams, or an inert bundle when off.

    Reads ``presence.rhythm.enabled`` (off by default): when off, returns an all-``None`` bundle
    so the hot path is byte-identical. When on, builds the shared share-of-voice gate (reactive
    ceiling + proactive throttle) over the episodic activity store and the natural-delay
    coordinator; the tunables live under ``presence.rhythm.*``.
    """
    presence = _section(config, "presence")
    rhythm = _section(presence, "rhythm")
    if not _flag(rhythm, "enabled"):
        return RhythmWiring()

    rhythm_config = _rhythm_config(rhythm)
    store = EpisodicOutgoingActivityStore(
        activity_provider, window_size=_int(rhythm, "window_size", _DEFAULT_WINDOW_SIZE)
    )
    gate = ShareOfVoiceGate(store, ShareOfVoicePolicy(config=rhythm_config))
    reply_delay = DelayedTurn(
        NaturalDelayPolicy(config=rhythm_config),
        sleep=asyncio.sleep,
        monotonic=time.monotonic,
    )
    return RhythmWiring(
        barge_ceiling=gate, reply_delay=reply_delay, share_ceiling=gate
    )
