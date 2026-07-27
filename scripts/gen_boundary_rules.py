#!/usr/bin/env python3
"""Generate per-module import-boundary rules for Bob's domain-first vertical modules.

Reads the `module-vertical` nodes from ``.beadloom/_graph/services.yml`` and emits,
for each module, a set of explicit-path ``forbid_import`` rules into the
marker-delimited region of ``.beadloom/_graph/rules.yml``:

    # BEGIN generated boundary rules
    ...generated rules...
    # END generated boundary rules

EXPLICIT paths (not fnmatch char-classes) are the whole point: the previous scheme
isolated a module with a single-char class such as ``src/bob/[adimp]*`` — but
``capabilities`` starts with ``c`` exactly like ``coding``, so a char-class cannot
tell them apart (fnmatch keys off the first letter). Explicit ``src/bob/<module>/``
sources dodge that collision entirely.

Rendering is deterministic (modules + sources sorted by ref_id), so the write is
idempotent and ``--check`` (CI gate) can verify the region is in sync. Hand-authored
rationale/note blocks live OUTSIDE the markers and are never touched.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = REPO_ROOT / ".beadloom" / "_graph"
SERVICES_YML = GRAPH_DIR / "services.yml"
RULES_YML = GRAPH_DIR / "rules.yml"

BEGIN_MARKER = "  # BEGIN generated boundary rules"
END_MARKER = "  # END generated boundary rules"

# Clean-Architecture horizontal layers — always potential inbound sources for a
# module boundary (a module must never be reached from a horizontal layer except
# through its public façade/ports).
HORIZONTAL_LAYERS = ("application", "domain", "infrastructure")


def load_modules() -> list[tuple[str, str]]:
    """Return sorted ``(ref_id, source_dir)`` pairs for every module-vertical node."""
    data = yaml.safe_load(SERVICES_YML.read_text(encoding="utf-8"))
    modules: list[tuple[str, str]] = []
    for node in data.get("nodes", []):
        if "module-vertical" in node.get("tags", []):
            modules.append((node["ref_id"], node["source"].rstrip("/")))
    return sorted(modules)


def usecases_reexports(source_dir: str) -> bool:
    """True iff ``<module>/usecases/__init__.py`` re-exports (has import statements).

    Drives the ``internals-no-usecases`` source glob: a façade ``__init__`` means
    LEGAL usecase↔usecase sibling re-exports, so the ``usecases/`` dir must be
    excluded from the source via ``[!u]*``; an inert ``__init__`` allows a plain ``*``.
    """
    init = REPO_ROOT / source_dir / "usecases" / "__init__.py"
    if not init.exists():
        return False
    return any(
        line.lstrip().startswith(("from ", "import "))
        for line in init.read_text(encoding="utf-8").splitlines()
    )


def _rule(name: str, description: str, from_glob: str, to_glob: str) -> list[str]:
    """Render one ``forbid_import`` rule as YAML list-item lines."""
    return [
        f"  - name: {name}",
        f'    description: "{description}"',
        "    severity: error",
        f'    forbid_import: {{from: "{from_glob}", to: "{to_glob}"}}',
    ]


def render(modules: list[tuple[str, str]]) -> str:
    """Render the full generated-region body (between, not including, the markers)."""
    all_sources = sorted({ref for ref, _ in modules} | set(HORIZONTAL_LAYERS))
    lines: list[str] = []
    for ref, source in modules:
        internals_src = (
            f"src/bob/{ref}/[!u]*" if usecases_reexports(source) else f"src/bob/{ref}/*"
        )
        lines.append("")
        lines.append(f"  # ── {ref} VERTICAL module (generated) ──")
        # Internal layering.
        lines += _rule(
            f"{ref}-usecases-no-adapters",
            f"{ref}: usecases не импортят adapters (порты; adapters — на композиции)",
            f"src/bob/{ref}/usecases/*",
            f"bob/{ref}/adapters/*",
        )
        lines += _rule(
            f"{ref}-internals-no-usecases",
            f"{ref}: доменная логика/адаптеры не импортят usecases (usecases — на композиции)",
            internals_src,
            f"bob/{ref}/usecases/*",
        )
        lines += _rule(
            f"{ref}-internals-no-adapters",
            f"{ref}: доменная логика не импортит adapters (adapters — на композиции)",
            f"src/bob/{ref}/[!au]*",
            f"bob/{ref}/adapters/*",
        )
        lines += _rule(
            f"{ref}-usecases-no-infra",
            f"{ref}: usecases не импортят чужой infrastructure (только через порты)",
            f"src/bob/{ref}/usecases/*",
            "bob/infrastructure/*",
        )
        lines += _rule(
            f"{ref}-no-composition-root",
            f"{ref}: модуль не импортит композиционный корень (src/bob/app.py)",
            f"src/bob/{ref}/*",
            "bob/app",
        )
        # Inward boundary: every OTHER top-level tree, listed explicitly (killing
        # the char-class correlation and the c/c collision).
        for src in all_sources:
            if src == ref:
                continue
            lines += _rule(
                f"{ref}-boundary-no-{src}-usecases",
                f"{ref}: {src} не импортит usecases напрямую (только через фасад/порты)",
                f"src/bob/{src}/*",
                f"bob/{ref}/usecases/*",
            )
            lines += _rule(
                f"{ref}-boundary-no-{src}-adapters",
                f"{ref}: {src} не импортит adapters напрямую (только через фасад/порты)",
                f"src/bob/{src}/*",
                f"bob/{ref}/adapters/*",
            )
    lines.append("")
    return "\n".join(lines)


def splice(original: str, body: str) -> str:
    """Replace the text between the BEGIN/END markers with ``body``."""
    lines = original.splitlines()
    begin = next((i for i, ln in enumerate(lines) if ln.rstrip() == BEGIN_MARKER), None)
    end = next((i for i, ln in enumerate(lines) if ln.rstrip() == END_MARKER), None)
    if begin is None or end is None or begin >= end:
        raise SystemExit(
            "marker region not found in rules.yml "
            f"({BEGIN_MARKER!r} / {END_MARKER!r})"
        )
    merged = lines[: begin + 1] + body.splitlines() + lines[end:]
    trailing = "\n" if original.endswith("\n") else ""
    return "\n".join(merged) + trailing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the generated region is in sync; exit 1 if stale (CI gate)",
    )
    args = parser.parse_args()

    modules = load_modules()
    current = RULES_YML.read_text(encoding="utf-8")
    updated = splice(current, render(modules))

    if args.check:
        if updated != current:
            sys.stderr.write(
                "rules.yml generated region is STALE — "
                "run: python scripts/gen_boundary_rules.py\n"
            )
            return 1
        sys.stdout.write("rules.yml generated region is in sync\n")
        return 0

    if updated != current:
        RULES_YML.write_text(updated, encoding="utf-8")
        sys.stdout.write(
            f"rules.yml: regenerated boundary region for {len(modules)} module(s)\n"
        )
    else:
        sys.stdout.write("rules.yml: boundary region already up to date\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
