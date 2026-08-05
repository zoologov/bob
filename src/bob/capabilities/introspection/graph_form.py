# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure request core for the read-only ``beadloom graph`` / ``why`` reads (BOB-091.1).

ONE responsibility: shape a read-only beadloom graph REQUEST — decide which of the
THREE allowed invocation forms answers what was asked, validate every dynamic slot
that will reach argv, and judge whether the answer actually carries a diagram (so a
detailed form with nothing to show can honestly fall back to a simpler one).

Why it is a fixed-form planner and not a flag passthrough: ``beadloom graph`` accepts
``--project`` (another repo), ``--json``, ``--format c4-plantuml`` and more, and the
CLI as a whole has WRITE subcommands (``reindex`` / ``docs`` / ``link`` / ``setup-*``).
If the model could choose flags, "draw me the architecture" would become an arbitrary
CLI call. So the forms are enumerated here — the whole map, one node (optionally with
a bounded ``--depth``), or the C4 components inside one container — and the adapter
membership-checks the resulting argv against the same shapes BEFORE exec. A ref slot is
validated to a strict graph-ref shape (:func:`validate_graph_ref`), so a flag, a path,
a shell metacharacter or a second word can never occupy it; a depth is a clamped
integer, never a caller-chosen string.

🔴 The fallback exists because of a LIVE fact, not a hypothesis:
``graph --format c4 --level component --scope <ref>`` prints a lone ``C4Container``
header when the ref is a LEAF of the graph (``memory``) — internals exist only for a
container (``bob`` / ``bob-domain``). Without the fallback the owner would get an empty
picture; with it he gets that node's real links, and the capability says which form it
actually drew (never passing one off as the other).

Pure functions: no subprocess, no disk, no LLM. This is the mutation-tested core; the
subprocess reads live behind the :class:`~bob.capabilities.ports.RepoIntrospector` port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# A graph ref-id: a lower-case word, optionally hyphen/dot-joined (``memory``,
# ``bob-domain``, ``runtime-app``, ``bob-cjz.1``). Anchored and separator-strict, so a
# flag (``--json``), a path (``../etc``), a shell metacharacter (``;``), whitespace or a
# second word never matches — this regex IS the injection guard for the ref slot.
_GRAPH_REF_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-.][a-z0-9]+)*$")

# Upper bound on a ref's length: real ref-ids are short, and a longer value carries no
# extra signal — only a wider argv surface.
_MAX_REF_CHARS = 64

# Traversal-depth bounds for the node form. Zero/negative would ask beadloom for "no
# graph at all", and an unbounded depth is just the overview by a longer road.
_MIN_GRAPH_DEPTH = 1
MAX_GRAPH_DEPTH = 5

# The FIXED tail of the C4-components form. Modelled as one tuple (like
# ``_BD_SEARCH_TAIL_FORM`` in the adapter) so no other ``--format`` / ``--level`` is
# expressible: the scope ref is the only slot, and it is validated.
_C4_COMPONENTS_PREFIX: tuple[str, ...] = (
    "--format",
    "c4",
    "--level",
    "component",
    "--scope",
)
# The literal flag of the bounded node form (its value is a clamped integer).
_DEPTH_FLAG = "--depth"

GraphFormKind = Literal["overview", "node", "components"]


@dataclass(frozen=True)
class GraphForm:
    """One allowed ``beadloom graph`` invocation: its ``kind`` and exact ``args``.

    ``kind`` names the shape for the answer Bob gives ("это общая схема" vs "это
    внутренности контейнера"), ``args`` is the fully-resolved argument tuple the
    adapter membership-checks and runs, and ``fallback`` is the honest simpler form to
    run when this one draws nothing (``None`` when there is nothing simpler to try).
    """

    kind: GraphFormKind
    args: tuple[str, ...]
    fallback: GraphForm | None = None


def is_graph_ref(raw: str) -> bool:
    """Whether ``raw`` (trimmed, case-folded) is a strict graph ref-id.

    The non-raising twin of :func:`validate_graph_ref`, exposed so a caller can ROUTE
    on the shape ("did the model send a ref at all?") without an exception.
    """
    token = raw.strip().lower()
    if not token or len(token) > _MAX_REF_CHARS:
        return False
    return bool(_GRAPH_REF_RE.match(token))


def validate_graph_ref(raw: str) -> str:
    """Return ``raw`` normalised to a graph ref-id, or raise :class:`ValueError`.

    Trims and lower-cases (ref-ids are lower-case, so normalising the case answers the
    question instead of refusing it) and then enforces the strict shape. A flag, a
    path, a shell metacharacter, embedded whitespace, an over-long value or an empty
    one raises — this is the guard for every ref that reaches ``beadloom graph``/``why``.
    """
    token = raw.strip().lower()
    if not is_graph_ref(token):
        raise ValueError(f"not a valid graph ref: {raw!r}")
    return token


def clamp_graph_depth(depth: int) -> int:
    """Return ``depth`` clamped into ``[1, MAX_GRAPH_DEPTH]`` (always a real traversal)."""
    return max(_MIN_GRAPH_DEPTH, min(depth, MAX_GRAPH_DEPTH))


def diagram_carries_nodes(source: str) -> bool:
    """Whether a diagram source declares anything beyond its own header line.

    ``beadloom graph`` answers an unresolved ref with a bare ``graph LR`` and a
    ``--scope`` that has no internals with a bare ``C4Container``. Both are headers with
    NOTHING under them — a picture of nothing. Blank lines do not count as content, so
    this is the honest "did we get a diagram?" question.
    """
    return len([line for line in source.splitlines() if line.strip()]) > 1


def _overview_form() -> GraphForm:
    """The whole-map form: ``beadloom graph`` with no arguments."""
    return GraphForm(kind="overview", args=())


def _node_form(ref: str, depth: int | None) -> GraphForm:
    """The one-node form: ``<ref>`` plus a bounded ``--depth`` when one was asked."""
    if depth is None:
        return GraphForm(kind="node", args=(ref,))
    return GraphForm(
        kind="node", args=(ref, _DEPTH_FLAG, str(clamp_graph_depth(depth)))
    )


def _components_form(scope: str) -> GraphForm:
    """The C4-components form for one container, falling back to that node's links."""
    return GraphForm(
        kind="components",
        args=(*_C4_COMPONENTS_PREFIX, scope),
        fallback=_node_form(scope, None),
    )


def plan_graph_form(
    ref: str | None = None,
    *,
    depth: int | None = None,
    internals_of: str | None = None,
) -> GraphForm:
    """Plan the allowed ``beadloom graph`` form that answers this request.

    Precedence, most specific first: ``internals_of`` (a container's C4 components) →
    ``ref`` (that node's neighbourhood, with a clamped ``depth`` when given) → the
    whole-map overview. A blank/absent value means "not asked" (an empty string from a
    model is not a broken ref); a NON-blank value that is not a graph ref-id raises
    :class:`ValueError` rather than silently answering a different question.
    """
    scope = internals_of.strip() if internals_of is not None else ""
    if scope:
        return _components_form(validate_graph_ref(scope))
    node = ref.strip() if ref is not None else ""
    if node:
        return _node_form(validate_graph_ref(node), depth)
    return _overview_form()
