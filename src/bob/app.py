# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Thin re-export shim for the composition root, now living in :mod:`bob.runtime`.

Historically ``bob.app`` WAS the composition root (2819 lines). BOB-062.7a moved it into the
cohesive :mod:`bob.runtime` package (``composition`` / ``main`` / ``clock`` / ``config`` /
``wiring``) and relocated the inline adapters to their domain homes
(``infrastructure/telegram``, ``social/adapters``, ``coding/adapters``). This module stays as
a stable façade so the ``./bob`` launcher (``from bob.app import main``) and the existing
tests (``from bob.app import build_application`` / the ``_build_*`` factories) keep working
unchanged — every symbol below is re-exported from its new home.
"""

from __future__ import annotations

from bob.coding.adapters.owner_notifier import _CodingOwnerNotifier
from bob.infrastructure.telegram.aiogram_adapter import (
    _AiogramBotAdapter,
    _build_real_bot,
    _to_update_view,
)
from bob.infrastructure.telegram.outage_notifier import _GuppiOutageNotifier
from bob.runtime import Application, SystemClock, build_application
from bob.runtime.config import (
    _DEFAULT_ABSENCE_HINT_HOURS,
    _DEFAULT_RECENT_TURNS,
    _float,
    _int,
    _str,
)
from bob.runtime.main import main
from bob.runtime.wiring import (
    _build_absence_hint_hours,
    _build_consolidate_memory,
    _build_dedup_facts,
    _build_diagram_renderer,
    _build_floor_config,
    _build_floor_enabled,
    _build_recent_turns,
    _build_registry,
    _build_repeat_thresholds,
    _build_reranker,
    _build_safe_capabilities,
    _build_surface_old_freq,
    _diagram_send_as,
)
from bob.social.adapters.soul_loader import _load_soul

__all__ = [
    "_DEFAULT_ABSENCE_HINT_HOURS",
    "_DEFAULT_RECENT_TURNS",
    "Application",
    "SystemClock",
    "_AiogramBotAdapter",
    "_CodingOwnerNotifier",
    "_GuppiOutageNotifier",
    "_build_absence_hint_hours",
    "_build_consolidate_memory",
    "_build_dedup_facts",
    "_build_diagram_renderer",
    "_build_floor_config",
    "_build_floor_enabled",
    "_build_real_bot",
    "_build_recent_turns",
    "_build_registry",
    "_build_repeat_thresholds",
    "_build_reranker",
    "_build_safe_capabilities",
    "_build_surface_old_freq",
    "_diagram_send_as",
    "_float",
    "_int",
    "_load_soul",
    "_str",
    "_to_update_view",
    "build_application",
    "main",
]
