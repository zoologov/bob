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
decides which paths may be read and redacts personal data from tool output, and
:mod:`~bob.capabilities.introspection.dev_query` shapes every dynamic value before it
reaches a subprocess. Alongside them the tracker pair decides and condenses what Bob
reads from beads: :mod:`~bob.capabilities.introspection.tracker_intent` plans a
free-text question into a read-only ``bd`` form, and
:mod:`~bob.capabilities.introspection.tracker_digest` condenses a long search listing
into a chat-sized answer. The architecture pair does the same for the graph
(BOB-091.1): :mod:`~bob.capabilities.introspection.graph_form` plans which of the THREE
allowed ``beadloom graph`` forms answers a diagram request (and validates every argv
slot), and :mod:`~bob.capabilities.introspection.impact_digest` condenses ``beadloom
why`` from a Rich panel + ASCII tree into a two-list answer. All of it has no I/O; the
infrastructure adapter enforces it at the boundary before any read.
"""

from bob.capabilities.introspection.code_history import (
    feature_doc_dir,
    parse_bead_refs,
)
from bob.capabilities.introspection.dev_query import (
    clamp_commit_count,
    is_bead_id,
    normalize_status,
    sanitize_search_term,
    validate_bead_id,
)
from bob.capabilities.introspection.graph_form import (
    GraphForm,
    clamp_graph_depth,
    diagram_carries_nodes,
    is_graph_ref,
    plan_graph_form,
    validate_graph_ref,
)
from bob.capabilities.introspection.impact_digest import digest_impact
from bob.capabilities.introspection.privacy_guard import PrivacyGuard
from bob.capabilities.introspection.tracker_digest import digest_search_results
from bob.capabilities.introspection.tracker_intent import (
    TrackerPlan,
    find_bead_key,
    plan_tracker_query,
)

__all__ = [
    "GraphForm",
    "PrivacyGuard",
    "TrackerPlan",
    "clamp_commit_count",
    "clamp_graph_depth",
    "diagram_carries_nodes",
    "digest_impact",
    "digest_search_results",
    "feature_doc_dir",
    "find_bead_key",
    "is_bead_id",
    "is_graph_ref",
    "normalize_status",
    "parse_bead_refs",
    "plan_graph_form",
    "plan_tracker_query",
    "sanitize_search_term",
    "validate_bead_id",
    "validate_graph_ref",
]
