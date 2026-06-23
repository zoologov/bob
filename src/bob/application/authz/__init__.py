# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Authorization policy — who may interact with Bob (owner + allowlist + chats)."""

from __future__ import annotations

from bob.application.authz.authorizer import Authorizer
from bob.application.authz.sender_perception import SenderPerception

__all__ = ["Authorizer", "SenderPerception"]
