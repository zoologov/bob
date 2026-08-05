# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=domain

"""Pure digest of the read-only beadloom health reports — «как дела у проекта».

ONE responsibility: condense ONE health report into an answer a person reads in a chat.
The six reports are shaped nothing alike, which is exactly why the condensing is a
per-report policy and not a generic truncation:

* ``status`` / ``doctor`` — human reports (Rich boxes, ``[ok]`` checklists): the
  decoration goes, and twelve ``[ok]`` lines collapse into their only information, the
  COUNT, while every complaint survives verbatim.
* ``sync-check`` — 585 pair lines / 48 KB in this repo: the fresh pairs become a number
  and only the ``[stale]`` ones are named.
* ``lint`` — a VERDICT: piped, the live CLI prints machine porcelain
  (``rule:kind:severity:file:line::``) and, when something IS broken, no summary line at
  all; the digest turns those tuples into readable lines.
* ``diff`` — the payload (``N added, M changed…``) is the LAST line, so a cap that only
  keeps the head would throw away the most useful sentence.
* ``prime`` — 39 KB, of which 224 lines are the rule list: the rules become a count and
  the agent-instruction sections are dropped (they are instructions for a tooling agent,
  not facts about the project).

Two honesty rules are structural, not decoration:

* 🔴 ``lint`` always carries the stored-index caveat. Bob reads the verdict WITHOUT
  reindexing (a reindex writes), and this project's own standing rule is that lint on an
  unrefreshed index LIES — so the answer says which index it was read off.
* 🔴 ``sync-check`` always carries the pairing caveat: the CLI builds pairs only for some
  node kinds, so "всё свежо" is not "все доки свежие".

Nothing is invented and nothing is silently dropped: a capped list states how many it
hid, and a report whose shape this module does not recognise comes back de-framed rather
than empty, so a future CLI change degrades to "less pretty" instead of "Bob knows
nothing". Deterministic, I/O-free.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

# Box/table glyphs Rich emits around ``status``. Stripped from both ends of every line:
# they are decoration. (Deliberately NOT shared with :mod:`.impact_digest`, whose tree
# glyphs carry NESTING and must be read before they are stripped — same characters,
# different meaning, so one shared stripper would blur two responsibilities.)
_GLYPHS = "╭╮╰╯│─┌┐└┘├┤┬┴┼ \t"

# How many items (complaints / stale pairs / violations) a list may name before the rest
# become a count. A dozen still reads as an answer. Public: the unit tests assert the
# bound rather than guessing it.
MAX_LISTED_ITEMS = 12

# Hard line cap for any digest — a chat answer never becomes a terminal dump.
MAX_REPORT_LINES = 50

# Upper bound on one kept ``prime`` line (a domain's description is the long one). Public:
# the unit tests assert the bound and its inclusive edge rather than guessing them.
MAX_DOMAIN_CHARS = 200

# ``doctor`` prints one ``  [<verdict>] <text>`` line per check.
_CHECK_RE = re.compile(r"^\[(?P<verdict>[a-z]+)\]\s+(?P<text>.+)$")
_PASSING_VERDICT = "ok"

# ``sync-check`` prints one ``  [ok|stale] <node>: <doc> <-> <src> [(<reason>)]`` line
# per doc↔code pair.
_PAIR_RE = re.compile(r"^\[(?P<verdict>ok|stale)\]\s+(?P<text>.+)$")
_STALE_VERDICT = "stale"

# ``lint`` piped: ``<rule>:<kind>:<severity>:<file>:<line>::`` — five fields and a
# trailing empty pair. Parsed positionally, since the human summary line is ABSENT in
# exactly the case that matters (something is broken).
_VIOLATION_RE = re.compile(
    r"^(?P<rule>[\w-]+):(?P<kind>[\w-]+):(?P<severity>\w+):"
    r"(?P<file>[^:]+):(?P<line>\d+):"
)

# ``prime`` is markdown: ``## <Section>``. The rule list is replaced by its count; the
# agent-facing sections are dropped entirely.
_SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_RULES_SECTION = "Architecture Rules"
_DROPPED_SECTIONS = ("Key Commands", "Agent Instructions")

# 🔴 Bob cannot refresh the index (that would be a write), so the lint verdict is read
# off whatever was last indexed. Saying so is the difference between an answer and an
# overstatement.
_LINT_CAVEAT = (
    "Проверено по сохранённому индексу, без переиндексации (я только читаю) — если код "
    "менялся после последней индексации, вердикт может отставать."
)

# 🔴 The CLI pairs a doc with code only for some node kinds, so a clean report is not a
# guarantee about every doc in the repo.
_SYNC_CAVEAT = (
    "Учти: пары док↔код строятся не для всех узлов графа, поэтому «свежо» здесь — "
    "не гарантия для узлов без пары."
)


def _deframe(raw: str) -> list[str]:
    """Return ``raw``'s lines with box glyphs and blank lines stripped, content intact."""
    stripped = (line.strip(_GLYPHS) for line in raw.splitlines())
    return [line for line in stripped if line]


def _cap(lines: list[str]) -> list[str]:
    """Cap ``lines`` at :data:`MAX_REPORT_LINES`, stating what was hidden."""
    if len(lines) <= MAX_REPORT_LINES:
        return lines
    hidden = len(lines) - MAX_REPORT_LINES + 1
    return [*lines[: MAX_REPORT_LINES - 1], f"…ещё {hidden} строк(и) отчёта."]


def _listed(items: list[str]) -> list[str]:
    """Render at most :data:`MAX_LISTED_ITEMS` items as ``- <item>`` + a hidden count."""
    shown = [f"- {item}" for item in items[:MAX_LISTED_ITEMS]]
    hidden = len(items) - len(shown)
    if hidden:
        shown.append(f"- …и ещё {hidden}.")
    return shown


def _matched(lines: list[str], pattern: re.Pattern[str]) -> list[re.Match[str]]:
    """Return the pattern matches of ``lines``, in order (unmatched lines dropped)."""
    return [match for line in lines if (match := pattern.match(line)) is not None]


def _digest_doctor(lines: list[str]) -> list[str] | None:
    """``doctor``: how many checks passed, and every complaint verbatim."""
    checks = _matched(lines, _CHECK_RE)
    if not checks:
        return None
    passing = [c for c in checks if c["verdict"] == _PASSING_VERDICT]
    complaints = [
        f"{c['verdict']}: {c['text']}" for c in checks if c["verdict"] != _PASSING_VERDICT
    ]
    body = [f"Проверок графа пройдено: {len(passing)} из {len(checks)}."]
    if complaints:
        body.append(f"Замечания ({len(complaints)}):")
        body.extend(_listed(complaints))
    return body


def _digest_sync_check(lines: list[str]) -> list[str] | None:
    """``sync-check``: fresh pairs as a count, stale pairs by name."""
    pairs = _matched(lines, _PAIR_RE)
    if not pairs:
        return None
    stale = [p["text"] for p in pairs if p["verdict"] == _STALE_VERDICT]
    fresh = len(pairs) - len(stale)
    if stale:
        body = [
            f"Пар док↔код: {len(pairs)} — свежих {fresh}, устаревших {len(stale)}.",
            *_listed(stale),
        ]
    else:
        body = [f"Пар док↔код: {len(pairs)} — все свежие."]
    body.append(_SYNC_CAVEAT)
    return body


def _digest_lint(lines: list[str]) -> list[str] | None:
    """``lint``: the clean summary, or the porcelain tuples made readable."""
    violations = _matched(lines, _VIOLATION_RE)
    if violations:
        named = [
            f"{v['rule']} ({v['severity']}): {v['file']}:{v['line']}"
            for v in violations
        ]
        return [f"Нарушений: {len(violations)}.", *_listed(named), _LINT_CAVEAT]
    if any("violation" in line for line in lines):
        return [*lines, _LINT_CAVEAT]
    return None


def _digest_diff(lines: list[str]) -> list[str]:
    """``diff``: the changes, keeping the trailing counts line even when truncated."""
    if len(lines) <= MAX_REPORT_LINES:
        return lines
    hidden = len(lines) - MAX_REPORT_LINES + 1
    return [
        *lines[: MAX_REPORT_LINES - 2],
        f"…ещё {hidden} строк(и) изменений.",
        lines[-1],
    ]


def _capped_line(entry: str) -> str:
    """Cap one kept ``prime`` line (a domain description runs to a paragraph)."""
    if len(entry) <= MAX_DOMAIN_CHARS:
        return entry
    return entry[:MAX_DOMAIN_CHARS].rstrip() + "…"


def _digest_prime(lines: list[str]) -> list[str] | None:
    """``prime``: the headline facts, the rule COUNT, the domains, the health sections.

    One rule per line, so there is no "header lines are special" branch to get wrong: a
    line is kept unless its section is dropped, and every kept line is capped. The rule
    section is counted instead of listed — 224 rule names answer no question a person asked.
    """
    if not any(_SECTION_RE.match(line) for line in lines):
        return None
    body: list[str] = []
    section: str | None = None
    rules = 0
    for line in lines:
        heading = _SECTION_RE.match(line)
        if heading is not None:
            section = heading["title"]
            if section not in (*_DROPPED_SECTIONS, _RULES_SECTION):
                body.append(f"{section}:")
            continue
        if section == _RULES_SECTION:
            rules += 1
        elif section not in _DROPPED_SECTIONS:
            body.append(_capped_line(line))
    if rules:
        body.append(f"Правил архитектуры: {rules}.")
    return body


# The digests that PARSE a shape and can therefore DECLINE (return ``None``) when that
# shape was not in the output — the honest-degradation path back to plain de-framed text.
# ``status`` is absent on purpose: its digest IS "drop the Rich frames", which is exactly
# the fallback, so giving it an entry would only add a synonym.
_PARSING_DIGESTS: dict[str, Callable[[list[str]], list[str] | None]] = {
    "doctor": _digest_doctor,
    "sync-check": _digest_sync_check,
    "lint": _digest_lint,
    "prime": _digest_prime,
}


def digest_health(check: str, raw: str) -> str:
    """Condense the read-only beadloom report ``check`` into a chat-sized answer.

    Returns ``""`` for empty input (the caller answers honestly rather than inventing a
    report), the per-report digest when the live shape is recognised, and the de-framed
    text when it is not — so a CLI change or a future check degrades to "less pretty"
    instead of "Bob knows nothing".
    """
    if not raw.strip():
        return ""
    return "\n".join(_digest(check, _deframe(raw)))


def _digest(check: str, lines: list[str]) -> list[str]:
    """Dispatch to the report's own digest, degrading to the de-framed lines.

    ``diff`` caps ITSELF, because its payload is the last line and a head-cap would eat
    it; everything else is capped uniformly here. ``status`` and an unrecognised check
    share the same answer — the de-framed report — which is why neither has an entry.
    """
    if check == "diff":
        return _digest_diff(lines)
    parse = _PARSING_DIGESTS.get(check)
    body = lines if parse is None else (parse(lines) or lines)
    return _cap(body)
