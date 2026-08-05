# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure ``beadloom why`` digest (BOB-091.1).

``beadloom why memory`` prints 197 lines of Rich panel + ASCII tree with every node's
full description wrapped to 80 columns. In a Telegram message that is noise: the owner
asked "что сломается, если тронуть memory", and the answer is two short lists.
:func:`digest_impact` keeps the MEANING (subject, direct upstream, direct downstream,
an honest count of what lies deeper) and drops the graphics.

Pure: text in, text out. Mutation target of the slice.
"""

from __future__ import annotations

from bob.capabilities.introspection.impact_digest import (
    MAX_SUBJECT_CHARS,
    digest_impact,
)

# A faithful excerpt of real ``beadloom why memory`` output (glyphs, wrapping, the
# ``---- description`` separator and the nesting are copied from the live CLI).
_REAL_WHY = """\
╭────────────────────────────── Impact Analysis ───────────────────────────────╮
│ memory (feature)                                                             │
│ Memory module («Bob remembers») — the full vertical capability in one place:  │
│ `ports.py` + pure `entities`, `usecases/` (extract facts, consolidate,        │
│ dedup), and `adapters/` (FTS5/hybrid recall + local Ollama                    │
│ embedder/reranker). Domain-first slice BOB-062.2.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
Upstream (dependencies)
├── bob-domain (domain) ---- Domain layer umbrella: the seven module-vertical
│   bounded contexts (personality, conversation, memory, proactivity, coding,
│   capabilities, social) plus the shared `kernel` (infra-neutral cross-module
│   contracts). Pure logic + Protocol definitions; no I/O, no LLM, no transport.
│   └── bob (service) ---- Bob — Telegram-native companion agent: GUPPI process,
│       LLM Tier 0/1 router with privacy redaction, SQLite+FTS5 memory.
│       ├── coding (feature) ---- Coding module («Bob writes code») — the GATED
│       │   vertical (plan → approve → PR).
│       └── telegram (component) ---- Telegram adapter — aiogram gateway.
├── persistence (component) ---- Persistence kernel — the shared
│   `SqliteConnection` that the memory adapter reads through.
│   └── bob-infrastructure (domain) ---- Port adapters: aiogram Telegram gateway.
└── personality (feature) ---- Personality module («who Bob is»).

Downstream (dependents)
├── usecases (feature) ---- Use-cases — HandleMessage, RunGenesis.
│   └── llm (component) ---- LLM adapter — OpenAI-compatible provider.
├── coding (feature) ---- Coding module («Bob writes code»).
└── capabilities (feature) ---- Capabilities module («Bob's tools»).
"""


def test_subject_is_named_with_its_kind() -> None:
    digest = digest_impact(_REAL_WHY)

    assert digest.splitlines()[0].startswith("memory (feature)")


def test_subject_carries_its_description() -> None:
    digest = digest_impact(_REAL_WHY)

    assert "Memory module" in digest


def test_direct_upstream_nodes_are_listed() -> None:
    digest = digest_impact(_REAL_WHY)

    line = next(line for line in digest.splitlines() if line.startswith("Зависит от:"))
    assert "bob-domain (domain)" in line
    assert "persistence (component)" in line
    assert "personality (feature)" in line


def test_direct_downstream_nodes_are_listed() -> None:
    digest = digest_impact(_REAL_WHY)

    line = next(line for line in digest.splitlines() if line.startswith("Влияет на:"))
    assert "usecases (feature)" in line
    assert "capabilities (feature)" in line


def test_transitive_nodes_are_counted_not_listed_as_direct() -> None:
    # ``bob`` / ``telegram`` / ``bob-infrastructure`` / ``llm`` sit DEEPER in the tree —
    # claiming memory depends on them directly would be a false answer.
    digest = digest_impact(_REAL_WHY)

    upstream = next(line for line in digest.splitlines() if line.startswith("Зависит от:"))
    downstream = next(line for line in digest.splitlines() if line.startswith("Влияет на:"))
    for deeper in ("bob (service)", "telegram (component)", "llm (component)"):
        assert deeper not in upstream
        assert deeper not in downstream
    deeper_line = next(line for line in digest.splitlines() if line.startswith("Глубже"))
    assert "ещё 4" in deeper_line
    assert "bob" in deeper_line


def test_a_direct_relation_is_never_also_counted_as_deeper() -> None:
    # 🔴 Found on REAL output: ``coding`` is a DIRECT dependent of memory and also shows
    # up deep inside the upstream tree. Counting it twice would inflate "что ещё рядом"
    # and contradict the list right above it.
    digest = digest_impact(_REAL_WHY)

    deeper_line = next(line for line in digest.splitlines() if line.startswith("Глубже"))
    assert "coding" not in deeper_line


def test_labels_are_punctuated_once() -> None:
    # 🔴 Found on REAL output: the label carried its own colon and the renderer added
    # another («Зависит от::»).
    assert "::" not in digest_impact(_REAL_WHY)


def test_rich_frames_and_ascii_tree_are_gone() -> None:
    # 🔴 The whole point: a chat answer, not a terminal screenshot.
    digest = digest_impact(_REAL_WHY)

    for glyph in ("╭", "╮", "╰", "╯", "│", "├", "└", "──", "----"):
        assert glyph not in digest


def test_digest_is_short_enough_to_read_in_a_chat() -> None:
    digest = digest_impact(_REAL_WHY)

    assert len(digest.splitlines()) <= 5
    assert len(digest) < len(_REAL_WHY)


def test_headings_are_dropped() -> None:
    digest = digest_impact(_REAL_WHY)

    assert "Upstream (dependencies)" not in digest
    assert "Downstream (dependents)" not in digest


# --- honest degradations -------------------------------------------------------


def test_empty_output_digests_to_empty() -> None:
    # ``beadloom why nosuchref`` writes its error to stderr and leaves stdout empty;
    # the capability turns "" into an honest "не нашёл", so the digest must not invent.
    assert digest_impact("") == ""
    assert digest_impact("   \n\n") == ""


def test_unparseable_output_keeps_its_content() -> None:
    # A future CLI format change must never silently empty the answer: an unrecognised
    # shape comes back de-framed (glyphs stripped) but with its words intact.
    weird = "╭───╮\n│ something entirely new │\n╰───╯\nno tree here at all"

    digest = digest_impact(weird)

    assert "something entirely new" in digest
    assert "no tree here at all" in digest
    assert "│" not in digest


def test_leaf_node_is_reported_honestly_as_depended_on_by_nobody() -> None:
    raw = """\
╭─── Impact Analysis ───╮
│ presence (feature)    │
│ Presence module.      │
╰───────────────────────╯
Upstream (dependencies)
└── bob-domain (domain) ---- Domain layer umbrella.

Downstream (dependents)
"""
    digest = digest_impact(raw)

    assert "bob-domain (domain)" in digest
    downstream = next(line for line in digest.splitlines() if line.startswith("Влияет на:"))
    assert "никто" in downstream


def test_long_direct_list_is_capped_with_an_honest_tail() -> None:
    entries = "\n".join(
        f"├── node-{i} (feature) ---- Module number {i}." for i in range(20)
    )
    raw = (
        "╭─── Impact Analysis ───╮\n"
        "│ hub (feature)         │\n"
        "╰───────────────────────╯\n"
        "Upstream (dependencies)\n"
        f"{entries}\n"
        "\nDownstream (dependents)\n"
    )

    digest = digest_impact(raw)

    upstream = next(line for line in digest.splitlines() if line.startswith("Зависит от:"))
    assert "node-0 (feature)" in upstream
    assert "node-19 (feature)" not in upstream
    assert "ещё 8" in upstream


# --- 🔴 mutation-driven: the seams the first pass left unasserted ---------------


def _panel(subject: str, *description_lines: str) -> str:
    """Build a Rich-panel header exactly as the CLI frames it."""
    framed = "\n".join(f"│ {line}" for line in (subject, *description_lines))
    return f"╭─── Impact Analysis ───╮\n{framed}\n╰───────────────────────╯"


def test_deframed_fallback_keeps_lines_apart() -> None:
    # The degradation must stay READABLE: lines are lines, not one glued run.
    weird = "╭───╮\n│ first thing │\n│ second thing │\n╰───╯"

    assert digest_impact(weird).splitlines() == ["first thing", "second thing"]


def test_wrapped_description_is_rejoined_with_single_spaces() -> None:
    raw = (
        _panel("memory (feature)", "Memory module —", "the full vertical", "capability.")
        + "\nUpstream (dependencies)\n└── bob-domain (domain) ---- Umbrella.\n"
        + "\nDownstream (dependents)\n"
    )

    assert digest_impact(raw).splitlines()[0] == (
        "memory (feature) — Memory module — the full vertical capability."
    )


def test_description_exactly_at_the_cap_is_untouched() -> None:
    exact = "a" * MAX_SUBJECT_CHARS
    raw = (
        _panel("memory (feature)", exact)
        + "\nUpstream (dependencies)\n└── bob-domain (domain) ---- Umbrella.\n"
    )

    head = digest_impact(raw).splitlines()[0]

    assert head == f"memory (feature) — {exact}"
    assert "…" not in head


def test_over_long_description_is_cut_cleanly_with_an_ellipsis() -> None:
    # 60 five-char words: the cut lands right after a space, so a sloppy trim would leave
    # a dangling " …" in the middle of Bob's sentence.
    long_description = ("word " * 60).strip()
    raw = (
        _panel("memory (feature)", long_description)
        + "\nUpstream (dependencies)\n└── bob-domain (domain) ---- Umbrella.\n"
    )

    head = digest_impact(raw).splitlines()[0]

    assert head.endswith("…")
    assert not head.endswith(" …")
    assert head == f"memory (feature) — {long_description[:MAX_SUBJECT_CHARS].rstrip()}…"


def test_upstream_section_stops_at_the_downstream_heading() -> None:
    # 🔴 The sections must not bleed: a dependent listed below must never be reported as
    # something memory DEPENDS ON (that would invert the arrow of the whole answer).
    digest = digest_impact(_REAL_WHY)

    upstream = next(line for line in digest.splitlines() if line.startswith("Зависит от:"))
    assert "capabilities (feature)" not in upstream
    assert "usecases (feature)" not in upstream


def test_a_heading_that_directly_follows_an_entry_still_splits_the_sides() -> None:
    # No blank line between the last upstream entry and the Downstream heading: the
    # boundary is the heading itself, not the whitespace around it.
    raw = (
        _panel("memory (feature)", "Memory module.")
        + "\nUpstream (dependencies)\n"
        + "└── personality (feature) ---- Personality module.\n"
        + "Downstream (dependents)\n"
        + "└── capabilities (feature) ---- Capabilities module.\n"
    )

    digest = digest_impact(raw)

    upstream = next(line for line in digest.splitlines() if line.startswith("Зависит от:"))
    downstream = next(line for line in digest.splitlines() if line.startswith("Влияет на:"))
    assert upstream == "Зависит от: personality (feature)."
    assert downstream == "Влияет на: capabilities (feature)."


def test_lists_are_comma_separated_exactly() -> None:
    digest = digest_impact(_REAL_WHY)

    assert "bob-domain (domain), persistence (component), personality (feature)" in digest
    deeper_line = next(line for line in digest.splitlines() if line.startswith("Глубже"))
    assert "bob, telegram" in deeper_line


def test_both_empty_notes_are_the_exact_honest_wording() -> None:
    # The two "нечего сказать" answers are the load-bearing honest lines: «тронуть можно
    # свободно» vs «это корень». Their exact wording is what Bob repeats to the owner.
    only_downstream = (
        _panel("kernel (feature)", "Shared kernel.")
        + "\nUpstream (dependencies)\n"
        + "\nDownstream (dependents)\n"
        + "└── memory (feature) ---- Memory module.\n"
    )
    only_upstream = (
        _panel("presence (feature)", "Presence module.")
        + "\nUpstream (dependencies)\n"
        + "└── bob-domain (domain) ---- Umbrella.\n"
        + "\nDownstream (dependents)\n"
    )

    assert "Зависит от: ни от кого." in digest_impact(only_downstream)
    assert "Влияет на: никто не зависит." in digest_impact(only_upstream)


def test_a_tree_without_a_panel_degrades_instead_of_crashing() -> None:
    # 🔴 Both conditions of the guard matter: entries WITHOUT a subject panel cannot be
    # rendered as "<subject> — …", so the answer degrades to de-framed text.
    raw = (
        "Upstream (dependencies)\n"
        "└── bob-domain (domain) ---- Domain layer umbrella.\n"
        "\nDownstream (dependents)\n"
        "└── capabilities (feature) ---- Capabilities module.\n"
    )

    digest = digest_impact(raw)

    assert "bob-domain (domain)" in digest
    assert "Зависит от:" not in digest


def test_an_unframed_subject_does_not_swallow_the_tree_into_its_description() -> None:
    # 🔴 If the panel frame is ever absent, the description must still END where the
    # content begins — otherwise the whole tree lands inside Bob's opening sentence.
    raw = (
        "memory (feature)\n"
        "Upstream (dependencies)\n"
        "├── bob-domain (domain) ---- Domain layer umbrella.\n"
        "\nDownstream (dependents)\n"
        "├── capabilities (feature) ---- Capabilities module.\n"
    )

    digest = digest_impact(raw)

    assert digest.splitlines()[0] == "memory (feature)"
    assert "Зависит от: bob-domain (domain)." in digest


def test_an_unframed_subject_followed_by_an_entry_keeps_them_apart() -> None:
    raw = (
        "memory (feature)\n"
        "├── stray (component) ---- A node listed before any heading.\n"
        "Upstream (dependencies)\n"
        "├── bob-domain (domain) ---- Domain layer umbrella.\n"
        "Downstream (dependents)\n"
    )

    digest = digest_impact(raw)

    assert digest.splitlines()[0] == "memory (feature)"
    assert "stray" not in digest


def test_a_second_subject_line_ends_the_description() -> None:
    raw = (
        "memory (feature)\n"
        "presence (feature)\n"
        "Upstream (dependencies)\n"
        "├── bob-domain (domain) ---- Domain layer umbrella.\n"
        "Downstream (dependents)\n"
    )

    assert digest_impact(raw).splitlines()[0] == "memory (feature)"
