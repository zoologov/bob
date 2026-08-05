# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit tests for the pure project-health digest (BOB-091.2).

Every fixture here is a VERBATIM excerpt of what the real ``beadloom`` printed in this
repository (captured before a line of code was written, CLAUDE.md §0.3 п.4) — including
the two shapes a fake would never have produced:

* ``lint`` prints PORCELAIN when piped (``rule:kind:severity:file:line::``) and, in that
  case, no "N violations" summary line at all;
* ``sync-check`` prints 585 pair lines, so the digest's job is to COUNT the ``[ok]`` ones
  and name only the ``[stale]`` ones.

The digest is the second mutation target of the slice: raw report in, chat answer out.
"""

from __future__ import annotations

import pytest

from bob.capabilities.introspection.health_digest import (
    MAX_DOMAIN_CHARS,
    MAX_LISTED_ITEMS,
    MAX_REPORT_LINES,
    digest_health,
)

# --- real captured output (this repo, 2026-08-05) -------------------------------

REAL_STATUS = """
╭────────────────────────────── Beadloom v2.1.0 ───────────────────────────────╮
│ Last reindex: 2026-08-05T16:43:45.091650+00:00                               │
╰──────────────────────────────────────────────────────────────────────────────╯

  Nodes: 22    Edges: 105    Docs: 23    Symbols: 1453

    By Kind
 feature    13
 component   4

       Doc Coverage
 Overall    22/22 (100%)

        Health
 Stale docs       0
 Isolated nodes   0
""".lstrip("\n")

REAL_DOCTOR = """  [ok] All nodes have summaries.
  [warn] Doc 'getting-started.md' has no ref_id — unlinked from graph.
  [ok] All nodes have documentation.
  [ok] No isolated nodes.
  [ok] No symbol drift detected.
  [warn] Package drift: claimed but missing: application, capabilities
  [ok] CLI has 31 commands registered.
"""

REAL_SYNC_FRESH = """  [ok] bob: architecture.md <-> src/bob/application/reliability.py
  [ok] bob: architecture.md <-> src/bob/application/router/llm_router.py
  [ok] social: domains/social/README.md <-> src/bob/social/roster.py
"""

REAL_SYNC_STALE = """  [ok] bob: architecture.md <-> src/bob/application/reliability.py
  [stale] bob: architecture.md <-> src/bob/capabilities/ports.py (hash_changed)
  [ok] social: domains/social/README.md <-> src/bob/social/roster.py
  [stale] bob: architecture.md <-> src/bob/runtime/wiring/parameters.py (hash_changed)
"""

REAL_LINT_CLEAN = "0 violations, 224 rules evaluated\n"

REAL_LINT_PORCELAIN = (
    "capabilities-internals-no-adapters:forbid_import:error:"
    "src/bob/capabilities/introspection/_tmp_probe_violation.py:2::\n"
)

REAL_DIFF_NONE = "No graph changes since HEAD~1.\n"

REAL_DIFF_CHANGED = """Graph diff (since 66aa620~1):

Nodes:
  ~ coding (feature)
    Coding module («Bob writes code») — the full vertical capability in one
place: `ports.py` + pure domain logic, `usecases/` orchestration.
  + interactive (feature)

Edges:
  + interactive ----> bob-domain

1 added, 1 changed, 0 removed nodes; 1 added, 0 removed edges
"""

REAL_PRIME = """# Project: bob

Architecture: 3 domains, 2 services, 13 features | 1453 symbols
Health: 0 stale docs, 0 lint violations | Last reindex: 2026-08-05T16:43:45

## Architecture Rules
- domain-needs-parent (require): Каждый domain-узел (слой) — part_of сервиса bob
- feature-needs-parent (require): Каждая feature — part_of своего слоя (kind domain)
- no-dependency-cycles (forbid_cycles): Никаких циклов depends_on между узлами

## Key Commands
| Command | Description |
|---------|-------------|
| `beadloom ctx <ref_id>` | Full context bundle for a node |

## Agent Instructions
- Before work: call `get_context(ref_id)` or `prime` MCP tool
- After code changes: call `sync_check()`, update stale docs

## Domains
- bob-application: GUPPI orchestration: AgentRuntime + AsyncEventBus, LLMRouter.
- bob-domain: Domain layer umbrella: the seven module-vertical bounded contexts.

## Stale Docs
(none)

## Lint Violations
(none)
"""


# --- nothing at all: an honest empty, never an invented report ------------------


@pytest.mark.parametrize("check", ["status", "prime", "doctor", "lint", "diff"])
@pytest.mark.parametrize("blank", ["", "   ", "\n\n"])
def test_an_empty_report_digests_to_nothing(check: str, blank: str) -> None:
    # The caller answers "не смог посмотреть" honestly; the digest must not fabricate.
    assert digest_health(check, blank) == ""


# --- status: the Rich boxes go, the numbers stay --------------------------------


def test_status_keeps_the_numbers_and_drops_the_terminal_graphics() -> None:
    out = digest_health("status", REAL_STATUS)

    assert "Beadloom v2.1.0" in out
    assert "Nodes: 22" in out
    assert "Edges: 105" in out
    assert "22/22 (100%)" in out
    assert "Last reindex: 2026-08-05T16:43:45.091650+00:00" in out
    for glyph in ("╭", "╰", "│", "─"):
        assert glyph not in out


def test_status_has_no_blank_lines_left() -> None:
    # Rich pads with blank lines; in a chat message they are wasted space.
    out = digest_health("status", REAL_STATUS)

    assert "\n\n" not in out
    assert all(line.strip() for line in out.splitlines())


# --- doctor: the passing checks become a count, the complaints stay verbatim ----


def test_doctor_counts_the_passing_checks_and_names_the_complaints() -> None:
    out = digest_health("doctor", REAL_DOCTOR)

    assert "5 из 7" in out
    assert "Doc 'getting-started.md' has no ref_id" in out
    assert "Package drift: claimed but missing: application, capabilities" in out


def test_doctor_drops_the_individual_ok_lines() -> None:
    # Twelve "[ok] ..." lines carry one bit of information between them: the count.
    out = digest_health("doctor", REAL_DOCTOR)

    assert "All nodes have summaries" not in out
    assert "[ok]" not in out


def test_doctor_all_clear_says_so_without_a_complaint_list() -> None:
    clean = "  [ok] All nodes have summaries.\n  [ok] No isolated nodes.\n"

    out = digest_health("doctor", clean)

    assert "2 из 2" in out
    assert "Замечания" not in out


def test_doctor_caps_a_flood_of_complaints_and_says_how_many_it_hid() -> None:
    flood = "".join(
        f"  [warn] problem number {i}\n" for i in range(MAX_LISTED_ITEMS + 5)
    )

    out = digest_health("doctor", flood)

    assert f"Замечания ({MAX_LISTED_ITEMS + 5}):" in out
    assert "и ещё 5" in out
    assert out.count("problem number") == MAX_LISTED_ITEMS


def test_doctor_of_an_unrecognised_shape_still_returns_the_content() -> None:
    # Honest degradation: a changed CLI must make the answer LESS pretty, not empty.
    out = digest_health("doctor", "something entirely new\n")

    assert "something entirely new" in out


# --- sync-check: 585 pair lines become one verdict ------------------------------


def test_sync_check_fresh_reports_the_pair_count_and_no_stale_list() -> None:
    out = digest_health("sync-check", REAL_SYNC_FRESH)

    assert "Пар док↔код: 3 — все свежие." in out
    assert "устаревших" not in out
    # 585 pair lines in this repo: not one of them is echoed when they are all fine.
    assert "architecture.md" not in out


def test_sync_check_stale_names_the_stale_pairs_only() -> None:
    out = digest_health("sync-check", REAL_SYNC_STALE)

    assert "свежих 2" in out
    assert "устаревших 2" in out
    assert "src/bob/capabilities/ports.py" in out
    assert "src/bob/runtime/wiring/parameters.py" in out
    # The fresh pairs are a number, not a list.
    assert "src/bob/social/roster.py" not in out


def test_sync_check_carries_the_honest_pairing_caveat() -> None:
    # 🔴 The CLI only pairs feature/service nodes, so "всё свежо" is NOT the same as
    # "все доки свежие" — without this line Bob would overstate the verdict.
    out = digest_health("sync-check", REAL_SYNC_FRESH)

    assert "не для всех узлов" in out


def test_sync_check_caps_the_stale_list() -> None:
    flood = "".join(
        f"  [stale] bob: doc.md <-> src/mod{i}.py (hash_changed)\n"
        for i in range(MAX_LISTED_ITEMS + 3)
    )

    out = digest_health("sync-check", flood)

    assert "и ещё 3" in out
    assert out.count("hash_changed") == MAX_LISTED_ITEMS


def test_sync_check_of_an_unrecognised_shape_still_returns_the_content() -> None:
    out = digest_health("sync-check", "beadloom said something else\n")

    assert "beadloom said something else" in out


# --- lint: the two REAL shapes (summary vs porcelain) --------------------------


def test_lint_clean_keeps_the_verdict_line() -> None:
    out = digest_health("lint", REAL_LINT_CLEAN)

    assert "0 violations, 224 rules evaluated" in out


def test_lint_porcelain_becomes_a_readable_violation_list() -> None:
    # 🔴 The live shape when piped: no summary line at all, just machine tuples.
    out = digest_health("lint", REAL_LINT_PORCELAIN)

    assert "Нарушений: 1" in out
    assert "capabilities-internals-no-adapters" in out
    assert "error" in out
    assert "src/bob/capabilities/introspection/_tmp_probe_violation.py:2" in out
    # The machine separators do not survive into a chat answer.
    assert "::" not in out
    assert "forbid_import:error" not in out


def test_lint_counts_every_porcelain_violation() -> None:
    two = (
        "rule-a:forbid_import:error:src/one.py:2::\n"
        "rule-b:forbid_import:warn:src/two.py:9::\n"
    )

    out = digest_health("lint", two)

    assert "Нарушений: 2" in out
    assert "rule-a" in out
    assert "rule-b" in out
    assert "warn" in out


def test_lint_caps_the_violation_list_but_keeps_the_true_count() -> None:
    flood = "".join(
        f"rule-{i}:forbid_import:error:src/mod{i}.py:1::\n"
        for i in range(MAX_LISTED_ITEMS + 4)
    )

    out = digest_health("lint", flood)

    assert f"Нарушений: {MAX_LISTED_ITEMS + 4}" in out
    assert "и ещё 4" in out


def test_lint_always_carries_the_stored_index_caveat() -> None:
    # 🔴 Bob reads the verdict off the STORED index (he must not reindex — that writes),
    # and this repo's own rule is that an unrefreshed index makes lint LIE. Saying so is
    # the difference between an answer and an overstatement.
    for raw in (REAL_LINT_CLEAN, REAL_LINT_PORCELAIN):
        assert "сохранённому индексу" in digest_health("lint", raw)


def test_lint_of_an_unrecognised_shape_still_returns_the_content() -> None:
    out = digest_health("lint", "lint exploded in a new way\n")

    assert "lint exploded in a new way" in out


# --- diff: the summary line is the payload and must survive truncation ----------


def test_diff_without_changes_passes_the_verdict_through() -> None:
    out = digest_health("diff", REAL_DIFF_NONE)

    assert out.strip() == "No graph changes since HEAD~1."


def test_diff_with_changes_keeps_what_changed_and_the_summary() -> None:
    out = digest_health("diff", REAL_DIFF_CHANGED)

    assert "+ interactive (feature)" in out
    assert "1 added, 1 changed, 0 removed nodes; 1 added, 0 removed edges" in out


def test_a_long_diff_is_capped_to_exactly_the_line_budget() -> None:
    # The exact contract, not just "shorter": the head, one honest marker naming how many
    # lines it hid, and the trailing counts line.
    # Written with the CLI's own indentation, which the de-framing drops — the ``+`` / ``~``
    # markers are what carry the meaning, not the leading spaces.
    body = [f"+ node{index} (feature)" for index in range(MAX_REPORT_LINES + 9)]
    body.append("59 added, 0 changed, 0 removed nodes")

    out = digest_health("diff", "\n".join(f"  {line}" for line in body)).splitlines()

    assert len(out) == MAX_REPORT_LINES
    assert out[: MAX_REPORT_LINES - 2] == body[: MAX_REPORT_LINES - 2]
    hidden = len(body) - (MAX_REPORT_LINES - 1)
    assert out[-2] == f"…ещё {hidden} строк(и) изменений."
    assert out[-1] == body[-1]


def test_a_diff_at_exactly_the_line_budget_is_untouched() -> None:
    body = [f"+ node{index} (feature)" for index in range(MAX_REPORT_LINES)]

    out = digest_health("diff", "\n".join(f"  {line}" for line in body)).splitlines()

    assert out == body
    assert not any("ещё" in line for line in out)


def test_a_long_report_is_capped_to_exactly_the_line_budget() -> None:
    # Same exactness for every non-diff report (here: the de-framed fallback).
    body = [f"line number {index}" for index in range(MAX_REPORT_LINES + 20)]

    out = digest_health("status", "\n".join(body)).splitlines()

    assert len(out) == MAX_REPORT_LINES
    assert out[: MAX_REPORT_LINES - 1] == body[: MAX_REPORT_LINES - 1]
    hidden = len(body) - (MAX_REPORT_LINES - 1)
    assert out[-1] == f"…ещё {hidden} строк(и) отчёта."


def test_a_report_at_exactly_the_line_budget_is_untouched() -> None:
    body = [f"line number {index}" for index in range(MAX_REPORT_LINES)]

    out = digest_health("status", "\n".join(body)).splitlines()

    assert out == body


def test_a_long_diff_keeps_its_last_line_when_truncated() -> None:
    # 🔴 The counts live at the END of the report, so a head-only cap would throw away
    # the single most useful line.
    long_diff = "\n".join(f"  + node{i} (feature)" for i in range(200))
    long_diff += "\n200 added, 0 changed, 0 removed nodes"

    out = digest_health("diff", long_diff)

    assert out.splitlines()[-1] == "200 added, 0 changed, 0 removed nodes"
    assert len(out.splitlines()) < 60


# --- prime: 39 KB of which 224 lines are the rule list -------------------------


def test_prime_keeps_the_headline_facts() -> None:
    out = digest_health("prime", REAL_PRIME)

    assert "Architecture: 3 domains, 2 services, 13 features | 1453 symbols" in out
    assert "Health: 0 stale docs, 0 lint violations" in out


def test_prime_collapses_the_rule_list_to_a_count() -> None:
    out = digest_health("prime", REAL_PRIME)

    assert "Правил архитектуры: 3" in out
    assert "domain-needs-parent" not in out


def test_prime_keeps_the_domains_and_the_health_sections() -> None:
    out = digest_health("prime", REAL_PRIME)

    assert "bob-application" in out
    assert "bob-domain" in out
    assert "Stale Docs" in out
    assert "Lint Violations" in out


def test_prime_drops_the_agent_instruction_sections() -> None:
    # They are instructions aimed at a tooling agent, not facts about the project —
    # feeding them back into Bob's context is noise at best.
    out = digest_health("prime", REAL_PRIME)

    assert "Agent Instructions" not in out
    assert "Key Commands" not in out
    assert "MCP tool" not in out
    assert "beadloom ctx <ref_id>" not in out


def test_prime_caps_a_long_domain_description_at_the_exact_bound() -> None:
    entry = "- bob-domain: " + "очень длинно " * 60
    long_prime = f"# Project: bob\n\n## Domains\n{entry}\n"

    out = digest_health("prime", long_prime)

    capped = out.splitlines()[-1]
    # The cut is at the bound, the trailing space of the cut word is trimmed, and the
    # ellipsis is the ONLY thing appended — so the line reads as a sentence, not as debris.
    assert capped == entry[:MAX_DOMAIN_CHARS].rstrip() + "…"
    assert capped.endswith("…")
    assert not capped.endswith(" …")


def test_a_cut_landing_on_a_space_does_not_leave_a_gap_before_the_ellipsis() -> None:
    # The cut can fall exactly between words, and then the trailing space MUST go: a chat
    # line reading "…контексты …" looks like a bug in Bob, not like a shortened sentence.
    entry = "- bob-domain: " + "слово " * 60
    assert entry[:MAX_DOMAIN_CHARS].endswith(" "), "фикстура должна резать по пробелу"

    out = digest_health("prime", f"# Project: bob\n\n## Domains\n{entry}\n")

    capped = out.splitlines()[-1]
    assert capped.endswith("слово…")
    assert " …" not in capped


def test_a_domain_description_exactly_at_the_bound_is_not_capped() -> None:
    # The bound is inclusive on the legal side: a description of exactly the limit is a
    # whole sentence and must not be mutilated.
    entry = "- bob-domain: " + "x" * (MAX_DOMAIN_CHARS - len("- bob-domain: "))
    assert len(entry) == MAX_DOMAIN_CHARS

    out = digest_health("prime", f"# Project: bob\n\n## Domains\n{entry}\n")

    assert out.splitlines()[-1] == entry
    assert "…" not in out


def test_prime_of_an_unrecognised_shape_still_returns_the_content() -> None:
    out = digest_health("prime", "a brand new prime format\n")

    assert "a brand new prime format" in out


# --- an unknown check still degrades honestly -----------------------------------


def test_an_unknown_check_falls_back_to_de_framed_text() -> None:
    # The planner refuses unknown checks, so this is defence in depth: if a future check
    # arrives without a digest, the answer is plain text, never empty.
    out = digest_health("brand-new-report", "╭─────╮\n│ hi  │\n╰─────╯\n")

    assert out.strip() == "hi"


def test_every_digest_is_bounded_in_lines() -> None:
    # Whatever the check, a chat answer never becomes a terminal dump.
    flood = "".join(f"line number {i}\n" for i in range(2000))

    for check in ("status", "prime", "doctor", "sync-check", "lint", "diff"):
        assert len(digest_health(check, flood).splitlines()) <= 60
