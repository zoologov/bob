# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Introspection domain — the privacy invariant for Bob's read-only self-view.

Phase A (BOB-017) lets Bob inspect *his own world* — architecture, code, tracker —
read-only. This package holds the PURE policy that keeps that safe: the
:class:`~bob.capabilities.introspection.privacy_guard.PrivacyGuard` deterministically
decides which paths may be read and redacts personal data from tool output. It has
no I/O; the infrastructure adapter enforces it at the boundary before any read.
"""

from bob.capabilities.introspection.code_history import (
    feature_doc_dir,
    parse_bead_refs,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard

__all__ = ["PrivacyGuard", "feature_doc_dir", "parse_bead_refs"]
