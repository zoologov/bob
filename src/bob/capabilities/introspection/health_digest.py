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
  (``rule:kind:severity:file:line:from:to``) and, when something IS broken, no summary
  line at all; the digest turns those tuples into readable lines. 🔴 There are TWO real
  porcelain shapes, not one: a rule about a FILE fills file+line, and a rule about a NODE
  or an EDGE (cardinality / cycle / require / layer) leaves both EMPTY. Reading only the
  first shape was BOB-091.4's Critical-1 — the count said "1" while three rules were
  broken, and the raw tuple went out to the person as the answer.
* ``diff`` — the payload (``N added, M changed…``) is the LAST line, so a cap that only
  keeps the head would throw away the most useful sentence.
* ``prime`` — 39 KB, of which 224 lines are the rule list: the rules become a count and
  the agent-instruction sections are dropped (they are instructions for a tooling agent,
  not facts about the project).

Three honesty rules are structural, not decoration — each of them enforced where NO
branch can walk around it (BOB-091.4: the first two were promised by this docstring while
one of the two real ``lint`` shapes never reached them):

* 🔴 ``lint`` always carries the stored-index caveat. Bob reads the verdict WITHOUT
  reindexing (a reindex writes), and this project's own standing rule is that lint on an
  unrefreshed index LIES — so the answer says which index it was read off.
* 🔴 ``sync-check`` always carries the pairing caveat: the CLI builds pairs only for some
  node kinds, so "всё свежо" is not "все доки свежие".
  Both are appended by the DISPATCHER (:data:`_CAVEATS` in :func:`_digest`), not by a
  branch of one digest — that is what makes "always" a structure rather than a promise.
* 🔴 No machine tuple ever reaches the person. A porcelain line this module cannot read is
  COUNTED (so the verdict is never understated) and said out loud as unread — it is not
  dumped raw, because the raw dump is exactly what the digest exists to replace.

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

# ``lint`` piped prints one machine line per violation and NOTHING else (no summary line
# in exactly the case that matters — something is broken), so the tuple is read
# positionally: ``<rule>:<kind>:<severity>:<file>:<line>:<from>:<to>`` — SEVEN fields, of
# which only the first three are always filled.
#
# 🔴 file and line are EMPTY for every rule about a NODE or an EDGE — cardinality, cycle,
# require, layer (measured on the real CLI: a lowered symbol budget printed
# ``no-monster-modules-capabilities:cardinality:error:::capabilities:``, and a throw-away
# project printed ``no-dependency-cycles:cycle:error:::alpha:beta``). A pattern that
# demanded a file therefore did not SEE such a violation: the count said "1" while three
# rules were broken and the cycle vanished — the very defect class this project's §0.3
# rule 1 exists for. The location is whatever the line carries, and it may carry none.
_VIOLATION_FIELDS = 7
_FIELD_RE = re.compile(r"^[\w-]+$")

# A line that was NOT read as a violation but carries the machine field separator this
# thickly is porcelain of a shape this module does not know. It is COUNTED and owned up to,
# never echoed: handing a person a raw tuple is what the digest exists to prevent, and
# dropping it would understate the verdict. The threshold sits between the two real shapes
# of this command — porcelain has six colons, the human summary line has none.
_MACHINE_MIN_COLONS = 4

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

# 🔴 The two reports whose verdict OVERSTATES what the tool measured, and their caveats.
# Applied by the dispatcher (:func:`_digest`) rather than inside a digest, so no branch —
# not even the honest-degradation one for a shape this module fails to recognise — can
# walk around it. That was Critical-1's second half: the caveat existed in the code and the
# docstring promised it "always", while one of the two REAL output shapes never reached it.
_CAVEATS: dict[str, str] = {"lint": _LINT_CAVEAT, "sync-check": _SYNC_CAVEAT}

# What the verdict digest says instead of a machine dump when it cannot read the shape.
_UNREADABLE_LINES = "Ещё {count} строк(и) вердикта я не разобрал — формат вывода изменился."
_UNREADABLE_VERDICT = "Вердикт я получил, но не разобрал его формат."


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
        return [
            f"Пар док↔код: {len(pairs)} — свежих {fresh}, устаревших {len(stale)}.",
            *_listed(stale),
        ]
    return [f"Пар док↔код: {len(pairs)} — все свежие."]


def _location(file_path: str, line_no: str, from_ref: str, to_ref: str) -> str:
    """The most specific place a violation's slots point at, or ``""`` if none do.

    A file rule fills file (+ usually line); a node rule fills only ``from``; an edge rule
    (a cycle, a layer violation) fills BOTH ends — and naming both is the whole point:
    "memory" alone is not the fact, "memory → conversation" is.
    """
    if file_path:
        return f"{file_path}:{line_no}" if line_no else file_path
    if from_ref and to_ref:
        return f"{from_ref} → {to_ref}"
    return from_ref or to_ref


def _readable_violation(line: str) -> str | None:
    """Render ONE porcelain violation as a line a person reads, or ``None`` if it is not one.

    Positional by necessity (see :data:`_VIOLATION_FIELDS`) and tolerant of empty slots:
    only rule, kind and severity are always filled, and a rule about a node or an edge
    carries no file at all.
    """
    fields = line.split(":")
    if len(fields) != _VIOLATION_FIELDS:
        return None
    rule, kind, severity, file_path, line_no, from_ref, to_ref = fields
    if not all(_FIELD_RE.match(field) for field in (rule, kind, severity)):
        return None
    where = _location(file_path, line_no, from_ref, to_ref)
    named = f"{rule} ({severity})"
    return f"{named}: {where}" if where else named


def _digest_lint(lines: list[str]) -> list[str]:
    """``lint``: the verdict — every violation named, and never a machine tuple.

    🔴 Total on purpose (it never declines): declining handed the RAW porcelain to the
    person and lost the stored-index caveat on the way. So a line is either read as a
    violation, or — if it still looks like machine output — counted and owned up to, or
    passed through as the human text it is.
    """
    named: list[str] = []
    unreadable = 0
    human: list[str] = []
    for line in lines:
        readable = _readable_violation(line)
        if readable is not None:
            named.append(readable)
        elif _is_machine(line):
            unreadable += 1
        else:
            human.append(line)
    if not named and not unreadable:
        return human or [_UNREADABLE_VERDICT]
    body = [f"Нарушений: {len(named) + unreadable}.", *_listed(named)]
    if unreadable:
        body.append(_UNREADABLE_LINES.format(count=unreadable))
    return [*body, *human]


def _is_machine(line: str) -> bool:
    """Whether ``line`` is machine output — too many field separators to be a sentence."""
    return line.count(":") >= _MACHINE_MIN_COLONS


def _digest_diff(lines: list[str]) -> list[str]:
    """``diff``: the changes, keeping the trailing counts line even when truncated.

    A diff that fits is passed through whole. One that does not is first reduced to its
    SKELETON — every added/removed/changed entry, every ``tags:`` change, the section
    names and the counts line — because the CLI reprints a changed node's old AND new
    summary (a paragraph each), and two such nodes push every ``+`` entry past the
    budget: the owner asked what changed, and an added node IS the change while a
    reprinted paragraph is not (BOB-112, caught live). Each dropped description is owned
    up to with one marker per changed node, never silently. Only then is the head cap
    applied, with the same honest tail as before.
    """
    if len(lines) <= MAX_REPORT_LINES:
        return lines
    skeleton = _diff_skeleton(lines)
    if len(skeleton) <= MAX_REPORT_LINES:
        return skeleton
    hidden = len(skeleton) - MAX_REPORT_LINES + 1
    return [
        *skeleton[: MAX_REPORT_LINES - 2],
        f"…ещё {hidden} строк(и) изменений.",
        skeleton[-1],
    ]


# A node or edge entry of ``diff`` (de-framed): ``+ name (kind)``, ``- name (kind)``,
# ``~ name (kind)``, ``+ a --[kind]--> b`` / ``+ a ----> b``.
_DIFF_ENTRY_RE = re.compile(r"^[+~-] \S+( \([a-z][a-z-]*\)| --.*--> \S+)$")
# What else the skeleton keeps: the header, the section names, a tag change.
_DIFF_KEEP_RE = re.compile(r"^(Graph diff|Nodes:|Edges:|tags: )")
_DESCRIPTION_CHANGED = "описание изменено ({count} строк(и) скрыто)"


def _diff_skeleton(lines: list[str]) -> list[str]:
    """The structural lines of a de-framed ``diff``; dropped descriptions are marked once.

    The marker carries the COUNT of lines it stands for, so the reader knows how much
    was folded under it — the same honesty as the "…ещё N строк" tail.
    """
    kept: list[str] = []
    dropped = 0
    for line in lines[:-1]:
        if _DIFF_ENTRY_RE.match(line) or _DIFF_KEEP_RE.match(line):
            if dropped:
                kept.append(_DESCRIPTION_CHANGED.format(count=dropped))
                dropped = 0
            kept.append(line)
        elif line:
            dropped += 1
    if dropped:
        kept.append(_DESCRIPTION_CHANGED.format(count=dropped))
    return [*kept, lines[-1]]


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

    🔴 The caveat of a report that OVERSTATES (:data:`_CAVEATS`) is appended HERE, after
    the cap: that is what makes "always" true for every branch, including the degradation
    path, and keeps the caveat from being the line the cap throws away.
    """
    if check == "diff":
        return _digest_diff(lines)
    parse = _PARSING_DIGESTS.get(check)
    body = lines if parse is None else (parse(lines) or lines)
    caveat = _CAVEATS.get(check)
    capped = _cap(body)
    return capped if caveat is None else [*capped, caveat]
