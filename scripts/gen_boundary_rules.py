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

The same explicit-path discipline now extends to the per-module INTERNAL layering
rules (``internals-no-adapters`` / ``internals-no-usecases``). Those used a negated
char-class (``src/bob/<ref>/[!au]*`` / ``[!u]*``) to drop the ``adapters/`` +
``usecases/`` subtrees from the source — but fnmatch keys off the FIRST char, so the
class silently swallowed every ROOT file that happened to start with the same
letter (``conversation/addressivity.py``, ``personality/absence.py``,
``proactivity/urge.py`` — a/u root files that could then import their own adapters
UNDETECTED). We keep the char-class as an efficient base for the many entries that
do NOT collide, but every top-level entry whose first char is swallowed yet is NOT
the intentionally-dropped subtree is re-added as an EXPLICIT full-path source, and a
per-run coverage assertion (``_assert_internals_covered``) fails the build if any
root file is left uncovered — closing the a/u hole for good (BOB-062.8 .2).

Rendering is deterministic (modules + sources sorted by ref_id), so the write is
idempotent and ``--check`` (CI gate) can verify the region is in sync. Hand-authored
rationale/note blocks live OUTSIDE the markers and are never touched.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
GRAPH_DIR = REPO_ROOT / ".beadloom" / "_graph"
SERVICES_YML = GRAPH_DIR / "services.yml"
RULES_YML = GRAPH_DIR / "rules.yml"

BEGIN_MARKER = "  # BEGIN generated boundary rules"
END_MARKER = "  # END generated boundary rules"

# Inward-boundary layer sources — horizontal layers (OUTSIDE any vertical module)
# that must NOT reach into a module's usecases/adapters (only its public façade/
# ports). This is now EMPTY: the only member used to be the pure ``domain`` layer
# (``src/bob/domain/``), but BOB-062.8 .1 DELETED that last layer-first folder — its
# sole remaining content, the ports re-export shim, was removed and the 7 shared
# contracts moved to the ``src/bob/kernel/`` SHARED KERNEL. The kernel is
# deliberately NOT listed here: it imports from NO module (inward-safe by
# construction — modules → kernel is legal, kernel ↛ modules holds because the
# kernel pulls nothing), and it carries the plain ``feature`` kind (no
# ``module-vertical`` tag), so it is neither an isolation source nor an isolation
# target — no boundary rule forbids importing INTO it. The coordination layers
# (``application`` / ``infrastructure`` / ``runtime`` / the composition root) were
# always excluded on purpose: by definition they assemble and invoke modules'
# use-cases and adapters (cross-domain orchestration such as ``handle_message`` /
# ``privileged_fulfiller``; the infra composition of providers/factories). The
# inward boundary isolates BUSINESS modules from each other, not the coordinators
# that legitimately wire them together, and not the shared kernel every module
# rests on. Per-module internal layering (``usecases-no-infra`` /
# ``no-composition-root`` below) still keeps each module from reaching OUT to infra
# / the composition root.
INWARD_LAYER_SOURCES: tuple[str, ...] = ()


def load_modules() -> list[tuple[str, str]]:
    """Return sorted ``(ref_id, source_dir)`` pairs for every module-vertical node."""
    data = yaml.safe_load(SERVICES_YML.read_text(encoding="utf-8"))
    modules: list[tuple[str, str]] = []
    for node in data.get("nodes", []):
        if "module-vertical" in node.get("tags", []):
            modules.append((node["ref_id"], node["source"].rstrip("/")))
    return sorted(modules)


def _module_entries(source_dir: str) -> list[Path]:
    """Return the module's top-level entries (files + dirs), ``__pycache__`` aside."""
    root = REPO_ROOT / source_dir
    return sorted(p for p in root.iterdir() if p.name != "__pycache__")


def _internals_from_globs(
    ref: str, source_dir: str, swallowed_chars: str, drop_dirs: frozenset[str]
) -> tuple[str, list[tuple[str, str]]]:
    """Compute the source globs for an ``internals-*`` rule (explicit-path hardened).

    ``[!<swallowed_chars>]*`` is kept as an efficient BASE that drops the intended
    ``drop_dirs`` subtrees (they start with a swallowed char). But fnmatch keys off
    the first char, so the base ALSO swallows any root file / non-dropped subdir on
    a swallowed char. Each such entry is re-added as an EXPLICIT full path so no
    module internal escapes the rule.

    Returns ``(base_glob, [(suffix, patch_glob), ...])`` — base first, patches
    sorted by entry name; ``suffix`` disambiguates the emitted rule name.
    """
    base = f"src/bob/{ref}/[!{swallowed_chars}]*"
    patches: list[tuple[str, str]] = []
    for entry in _module_entries(source_dir):
        if entry.name in drop_dirs:
            continue
        if entry.name[0] not in swallowed_chars:
            continue  # already covered by the base char-class
        if entry.is_dir():
            patches.append((entry.name, f"src/bob/{ref}/{entry.name}/*"))
        elif entry.suffix == ".py":
            patches.append((entry.stem, f"src/bob/{ref}/{entry.name}"))
    return base, patches


def _assert_internals_covered(
    ref: str, source_dir: str, drop_dirs: frozenset[str], from_globs: list[str]
) -> None:
    """Fail the build if any module internal (root file / non-dropped subdir) is
    NOT matched by at least one emitted ``from`` glob — the a/u char-class hole."""
    for entry in _module_entries(source_dir):
        if entry.name in drop_dirs:
            continue
        if entry.is_dir():
            rep = f"src/bob/{ref}/{entry.name}/probe.py"
        elif entry.suffix == ".py":
            rep = f"src/bob/{ref}/{entry.name}"
        else:
            continue
        if not any(fnmatch.fnmatch(rep, g) for g in from_globs):
            raise SystemExit(
                f"gen_boundary_rules: internals rule for module '{ref}' does NOT "
                f"cover '{rep}' — char-class hole (regenerate the source globs)."
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
    all_sources = sorted({ref for ref, _ in modules} | set(INWARD_LAYER_SOURCES))
    lines: list[str] = []
    for ref, source in modules:
        lines.append("")
        lines.append(f"  # ── {ref} VERTICAL module (generated) ──")
        # Internal layering.
        lines += _rule(
            f"{ref}-usecases-no-adapters",
            f"{ref}: usecases не импортят adapters (порты; adapters — на композиции)",
            f"src/bob/{ref}/usecases/*",
            f"bob/{ref}/adapters/*",
        )
        # ``internals-no-usecases`` guards the module's DOMAIN + ADAPTERS (its non-
        # usecases internals) against reaching INTO usecases — the dependency
        # direction is usecases → domain, never the reverse. The ``usecases/`` dir
        # itself is dropped from the source (a usecase importing a SIBLING usecase is
        # a legal in-layer collaboration, NOT a violation of THIS rule). The base
        # ``[!u]*`` drops it efficiently; every OTHER u-prefixed root file (e.g.
        # ``proactivity/urge.py``) is re-added EXPLICITLY so the char-class no longer
        # swallows it (the a/u hole closed in BOB-062.8 .2).
        nou_base, nou_patches = _internals_from_globs(
            ref, source, swallowed_chars="u", drop_dirs=frozenset({"usecases"})
        )
        lines += _rule(
            f"{ref}-internals-no-usecases",
            f"{ref}: доменная логика/адаптеры не импортят usecases (usecases — на композиции)",
            nou_base,
            f"bob/{ref}/usecases/*",
        )
        for suffix, patch in nou_patches:
            lines += _rule(
                f"{ref}-internals-no-usecases-{suffix}",
                f"{ref}: root-файл {suffix} не импортит usecases (a/u-hole patch)",
                patch,
                f"bob/{ref}/usecases/*",
            )
        _assert_internals_covered(
            ref, source, frozenset({"usecases"}), [nou_base, *(p for _, p in nou_patches)]
        )
        # ``internals-no-adapters`` guards the module's pure domain from importing
        # its own adapters (adapters are wired at composition). The ``adapters/``
        # subtree is dropped (an adapter importing a SIBLING adapter is legal intra-
        # layer composition); ``usecases/`` is also dropped here (usecases→adapters is
        # covered by ``usecases-no-adapters`` above). The base ``[!au]*`` drops both
        # efficiently; every OTHER a/u root file (``conversation/addressivity.py``,
        # ``personality/absence.py``, ``proactivity/urge.py``) is re-added EXPLICITLY.
        noa_base, noa_patches = _internals_from_globs(
            ref, source, swallowed_chars="au", drop_dirs=frozenset({"adapters", "usecases"})
        )
        lines += _rule(
            f"{ref}-internals-no-adapters",
            f"{ref}: доменная логика не импортит adapters (adapters — на композиции)",
            noa_base,
            f"bob/{ref}/adapters/*",
        )
        for suffix, patch in noa_patches:
            lines += _rule(
                f"{ref}-internals-no-adapters-{suffix}",
                f"{ref}: root-файл {suffix} не импортит adapters (a/u-hole patch)",
                patch,
                f"bob/{ref}/adapters/*",
            )
        _assert_internals_covered(
            ref,
            source,
            frozenset({"adapters", "usecases"}),
            [noa_base, *(p for _, p in noa_patches)],
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
        # BOB-062.7a: the composition root moved app.py → the `bob/runtime`
        # package (composition/main/clock/config/wiring), so the app.py-shim ban
        # above no longer covers the real root. This companion rule forbids the
        # module from reaching the moved root directly. `bob/runtime*` catches both
        # the package (`bob.runtime`) and its submodules (`bob.runtime.composition`,
        # …); it does NOT collide with `bob.application.runtime` (that path is
        # `bob/application/runtime`, a different prefix). runtime → all modules stays
        # legal (composition root by definition) — no rule sources from runtime.
        lines += _rule(
            f"{ref}-no-runtime-root",
            f"{ref}: модуль не импортит композиционный корень (bob.runtime.*)",
            f"src/bob/{ref}/*",
            "bob/runtime*",
        )
        # Inward boundary: every OTHER business module + the pure ``domain`` layer,
        # listed explicitly (killing the char-class correlation and the c/c
        # collision). Coordination layers (application/infrastructure/runtime) are
        # NOT sources here — they legitimately orchestrate/compose modules.
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
