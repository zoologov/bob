# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure digest of ``beadloom why`` — who depends on this, and on whom does it depend.

ONE responsibility: condense the impact analysis of one graph node into an answer a
person reads in a chat. ``beadloom why memory`` prints 197 lines — a Rich panel, an
ASCII tree and every node's full description wrapped to 80 columns. The owner asked
"что сломается, если тронуть memory"; the answer is the subject, its DIRECT
dependencies, its DIRECT dependents, and an honest count of what lies deeper. The
graphics carry no meaning in Telegram, and pasting them back is exactly the wall of
text BOB-086 was fought over (the same reason :mod:`.tracker_digest` exists).

Nothing is invented and nothing is silently dropped: transitive nodes are COUNTED (a
node deeper in the tree is not a direct dependency — saying otherwise would be a false
answer), a capped list states how many it hid, and output whose shape this module does
not recognise comes back de-framed rather than empty, so a future CLI change degrades
to "less pretty" instead of "Bob knows nothing". Deterministic, I/O-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# One tree entry: ``<ref> (<kind>) <separator> <description>`` after its tree glyphs. The
# separator is what distinguishes an entry from a WRAPPED continuation line of the
# previous description (which carries no ref). beadloom ≤ 8 printed ``----``; 9.0.0 names
# the edge kind inside it — ``--[depends_on]--`` / ``--[part_of]--`` (BOB-112). Both are
# read: the edge kind carries no meaning for the owner's question, and the tree's nesting
# (not the kind) is what says direct vs transitive.
_ENTRY_RE = re.compile(
    r"^(?P<ref>[a-z][\w.-]*)\s+\((?P<kind>[a-z][a-z-]*)\)\s+(?:----|--\[[a-z_]+\]--)"
)

# The subject line inside the Rich panel: a bare ``<ref> (<kind>)`` with no description.
_SUBJECT_RE = re.compile(r"^(?P<ref>[a-z][\w.-]*)\s+\((?P<kind>[a-z][a-z-]*)\)$")

# The CLI's section headings (dropped from the digest — the Russian labels carry the
# same meaning in one word each).
_UPSTREAM_HEADING = "Upstream (dependencies)"
_DOWNSTREAM_HEADING = "Downstream (dependents)"

# Box-drawing + tree glyphs Rich emits. Stripped from both ends of every line: they are
# decoration, and in a chat they are noise.
_GLYPHS = "╭╮╰╯│─├└┌┐┘ \t"

# A DIRECT relation starts at column 0 with a branch marker; anything indented under it
# is transitive (a dependency of a dependency). Compared against the RAW line, since the
# glyphs are exactly what carries the nesting.
_BRANCH_MARKERS = ("├──", "└──")

# How many direct relations may be named per side. A dozen still reads as an answer.
MAX_IMPACT_ITEMS = 12
# How many transitive refs are named alongside their count (the rest stay a number).
_MAX_DEEPER_NAMED = 8
# Upper bound on the subject's description — enough to know what the node is. Public:
# the unit tests assert the bound (and its inclusive edge) rather than guessing it.
MAX_SUBJECT_CHARS = 200


@dataclass(frozen=True)
class _Node:
    """One graph node as the impact tree names it: its ref-id and its kind."""

    ref: str
    kind: str

    @property
    def label(self) -> str:
        """The node as a reader sees it: ``memory (feature)``."""
        return f"{self.ref} ({self.kind})"


@dataclass(frozen=True)
class _Relations:
    """One side of the impact tree: the DIRECT relations, plus the transitive ones."""

    direct: tuple[_Node, ...]
    deeper: tuple[_Node, ...]


def _deframe(raw: str) -> str:
    """Return ``raw`` with box/tree glyphs and blank lines stripped — content intact.

    The honest degradation: when the digest cannot parse the CLI's shape it still
    removes the decoration instead of returning nothing.
    """
    stripped = (line.strip(_GLYPHS) for line in raw.splitlines())
    return "\n".join(line for line in stripped if line)


def _subject(lines: list[str]) -> tuple[_Node, str] | None:
    """Return the panel's ``(node, description)``, or ``None`` if there is no panel.

    The subject is the first framed line that is a bare ``<ref> (<kind>)``; every framed
    line after it is a wrapped piece of its description, rejoined and length-capped.
    """
    for index, line in enumerate(lines):
        match = _SUBJECT_RE.match(line.strip(_GLYPHS))
        if match is None:
            continue
        node = _Node(ref=match["ref"], kind=match["kind"])
        return node, _description(lines[index + 1 :])
    return None


def _ends_the_description(text: str) -> bool:
    """Whether a de-glyphed line is no longer part of the subject's description.

    The panel's own border strips to nothing, which is how the real CLI shape ends. The
    other three cases matter when the frame is MISSING (a degraded/changed output): a
    section heading, a second subject line, or a tree entry must never be swallowed into
    the subject's description — that would put the tree inside Bob's sentence. Each case
    is a separate clause on purpose, so dropping one is a visible mutant.
    """
    return (
        not text
        or text in (_UPSTREAM_HEADING, _DOWNSTREAM_HEADING)
        or bool(_SUBJECT_RE.match(text))
        or bool(_ENTRY_RE.match(text))
    )


def _description(rest: list[str]) -> str:
    """Rejoin the panel's wrapped description lines, capped for a chat."""
    words: list[str] = []
    for line in rest:
        text = line.strip(_GLYPHS)
        if _ends_the_description(text):
            break
        words.append(text)
    joined = " ".join(words)
    if len(joined) <= MAX_SUBJECT_CHARS:
        return joined
    return joined[:MAX_SUBJECT_CHARS].rstrip() + "…"


def _section(lines: list[str], heading: str, end: str | None) -> list[str]:
    """Return the lines between ``heading`` and ``end`` (to the tail when ``end`` is None)."""
    start = _index_of(lines, heading)
    if start is None:
        return []
    rest = lines[start + 1 :]
    if end is None:
        return rest
    stop = _index_of(rest, end)
    return rest if stop is None else rest[:stop]


def _index_of(lines: list[str], heading: str) -> int | None:
    """Return the index of the line equal to ``heading`` (trimmed), or ``None``."""
    for index, line in enumerate(lines):
        if line.strip() == heading:
            return index
    return None


def _relations(lines: list[str]) -> _Relations:
    """Split one section's entries into direct relations and transitive ones.

    Order is preserved and duplicates are dropped. A ref mentioned twice at the SAME
    level collapses to its first mention; a ref that is direct here and also appears
    deeper is reconciled by :func:`_transitive`, which drops every direct ref (of BOTH
    sides) from the transitive tail.
    """
    direct: dict[str, _Node] = {}
    deeper: dict[str, _Node] = {}
    for line in lines:
        match = _ENTRY_RE.match(line.strip(_GLYPHS))
        if match is None:
            continue
        ref = match["ref"]
        bucket = direct if line.startswith(_BRANCH_MARKERS) else deeper
        bucket.setdefault(ref, _Node(ref=ref, kind=match["kind"]))
    return _Relations(direct=tuple(direct.values()), deeper=tuple(deeper.values()))


def _render_side(label: str, relations: _Relations, empty: str) -> str:
    """Render one side as ``<label>: a (k), b (k), и ещё N.`` (or the empty note)."""
    if not relations.direct:
        return f"{label}: {empty}"
    shown = relations.direct[:MAX_IMPACT_ITEMS]
    parts = [node.label for node in shown]
    hidden = len(relations.direct) - len(shown)
    if hidden:
        parts.append(f"и ещё {hidden}")
    return f"{label}: {', '.join(parts)}."


def _render_deeper(nodes: tuple[_Node, ...]) -> str | None:
    """Render the transitive tail (``Глубже по цепочке: ещё 5 — bob, llm.``), or None."""
    if not nodes:
        return None
    named = ", ".join(node.ref for node in nodes[:_MAX_DEEPER_NAMED])
    return f"Глубже по цепочке: ещё {len(nodes)} — {named}."


def _transitive(
    subject: _Node, upstream: _Relations, downstream: _Relations
) -> tuple[_Node, ...]:
    """Return the nodes that are ONLY reachable through another node, deduped.

    🔴 Cross-side: a node named as a direct relation on EITHER side (and the subject
    itself) is dropped here — the live tree mentions a direct dependent again deep inside
    the upstream branch, and counting it twice would contradict the list right above.
    """
    named = {subject.ref} | {
        node.ref for node in (*upstream.direct, *downstream.direct)
    }
    deeper: dict[str, _Node] = {}
    for node in (*upstream.deeper, *downstream.deeper):
        if node.ref not in named:
            deeper.setdefault(node.ref, node)
    return tuple(deeper.values())


def digest_impact(raw: str) -> str:
    """Condense ``beadloom why`` output into a chat-sized impact answer.

    Returns ``""`` for empty input (the CLI writes its "not found" to stderr, so the
    caller can answer honestly), the four-line digest — subject, direct dependencies,
    direct dependents, the transitive count — when the shape is recognised, and the
    de-framed text when it is not.
    """
    if not raw.strip():
        return ""
    lines = raw.splitlines()
    subject = _subject(lines)
    upstream = _relations(_section(lines, _UPSTREAM_HEADING, _DOWNSTREAM_HEADING))
    downstream = _relations(_section(lines, _DOWNSTREAM_HEADING, None))
    if subject is None or not (upstream.direct or downstream.direct):
        return _deframe(raw)
    node, description = subject
    head = f"{node.label} — {description}" if description else node.label
    deeper = _render_deeper(_transitive(node, upstream, downstream))
    body = [
        head,
        _render_side("Зависит от", upstream, "ни от кого."),
        _render_side("Влияет на", downstream, "никто не зависит."),
    ]
    if deeper is not None:
        body.append(deeper)
    return "\n".join(body)
