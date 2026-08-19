# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Architecture guard: a boundary must catch the PACKAGE form of an import too.

🔴 BOB-109 / Issues #60. The generated ``forbid_import`` rules used to target
``bob/<mod>/adapters/*`` — a glob that needs a segment AFTER the slash. An import of
the **package** produces no such segment::

    from bob.capabilities.adapters.web_search_qwen import QwenWebSearch
    #      -> edge "bob/capabilities/adapters/web_search_qwen"  -> CAUGHT
    from bob.capabilities.adapters import web_search_qwen
    #      -> edge "bob/capabilities/adapters"                  -> MISSED

Both reach the same symbol, so the second was a working way around the boundary —
239 of 260 rules were blind to it.

This guard is deliberately written against **matching behaviour**, not against the
text of the rule file: it calls the very ``fnmatch`` that Beadloom's
``evaluate_import_boundary_rules`` uses, on the very edge string Beadloom builds
(``import_path.replace(".", "/")``). A test that merely grepped the YAML for a
trailing ``/*`` would be judging the FORM of the guard — the exact mistake this
whole class of defect is made of (CLAUDE.md §0.3 п.12).

The SUBJECTS come from the real tree (every ``src/bob/<mod>/{usecases,adapters}``
that actually exists), so a new module is covered the moment it appears.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_RULES_YML = _REPO_ROOT / ".beadloom" / "_graph" / "rules.yml"
_SRC_ROOT = _REPO_ROOT / "src" / "bob"

_RULE_RE = re.compile(
    r'- name: (?P<name>\S+)\n(?:.*\n)*?    forbid_import: '
    r'\{from: "(?P<from>[^"]+)", to: "(?P<to>[^"]+)"\}'
)


def _rules() -> list[tuple[str, str, str]]:
    """Every ``forbid_import`` rule as ``(name, from_glob, to_glob)``."""
    text = _RULES_YML.read_text(encoding="utf-8")
    return [(m["name"], m["from"], m["to"]) for m in _RULE_RE.finditer(text)]


def _guarded_layer_packages() -> list[str]:
    """Import paths of every real ``<mod>/usecases`` and ``<mod>/adapters`` package."""
    found: list[str] = []
    for layer_dir in sorted(_SRC_ROOT.glob("*/")):
        for layer in ("usecases", "adapters"):
            if (layer_dir / layer).is_dir():
                found.append(f"bob/{layer_dir.name}/{layer}")
    return found


def test_the_repo_actually_has_guarded_layer_packages() -> None:
    """Guard the guard: an empty subject list would make every check below vacuous."""
    packages = _guarded_layer_packages()
    assert len(packages) >= 10, f"expected the vertical modules' layers, got {packages}"


def test_every_rule_targeting_a_layer_also_catches_the_package_form() -> None:
    """A rule aimed at a layer must match the bare package, not only its submodules."""
    blind: list[str] = []
    for name, _from_glob, to_glob in _rules():
        for package in _guarded_layer_packages():
            submodule = f"{package}/some_module"
            # Only rules that actually aim at THIS layer are in scope.
            if not fnmatch.fnmatch(submodule, to_glob):
                continue
            if not fnmatch.fnmatch(package, to_glob):
                blind.append(f"{name}: to={to_glob!r} misses the package {package!r}")
    assert not blind, (
        "These boundary rules catch `from <pkg>.<mod> import X` but MISS "
        "`from <pkg> import <mod>` — the same access, waved through:\n  "
        + "\n  ".join(sorted(blind)[:20])
        + f"\n({len(blind)} blind rule/package pairs in total)"
    )


@pytest.mark.parametrize("layer", ["usecases", "adapters"])
def test_a_package_form_import_is_reachable_evidence(layer: str) -> None:
    """The package form is a REAL import shape, not a hypothetical one.

    Keeps the guard above honest: it asserts against a form that Python actually
    resolves to the same symbol, which is why missing it is a hole and not a nicety.
    """
    packages = [p for p in _guarded_layer_packages() if p.endswith(f"/{layer}")]
    assert packages, f"no {layer} packages found in the tree"
    for package in packages:
        assert (_SRC_ROOT.parent / package).is_dir()
        assert (_SRC_ROOT.parent / package / "__init__.py").is_file(), (
            f"{package} is a package, so `from {package.replace('/', '.')} import X` "
            "is a legal import shape a boundary must account for"
        )


def test_the_generated_region_is_in_sync_with_the_generator() -> None:
    """``gen_boundary_rules.py --check`` must actually be RUN by something.

    🔴 BOB-109. Its docstring calls ``--check`` "a CI gate", but nothing invoked it —
    not CI, not a hook, not a test. The region therefore drifted silently: when
    ``src/bob/coding/untrusted_repo.py`` was added (BOB-089, 2026-08-12) it needed an
    explicit a/u-hole patch rule, nobody regenerated, and for six days that root file
    could import its own ``usecases``/``adapters`` with the lint staying green.

    The generator already asserts its own coverage — but only while it RUNS. A guard
    that nothing executes is a guard on paper, the same shape as an allowlist entry
    with no caller (Issues #45). This test is the thing that executes it.
    """
    generator = _REPO_ROOT / "scripts" / "gen_boundary_rules.py"
    assert generator.is_file(), "the boundary-rule generator is missing"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(generator), "--check"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
    )
    assert result.returncode == 0, (
        "the generated boundary region is stale — run `python scripts/gen_boundary_rules.py`.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
