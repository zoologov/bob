# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Guard the composition-root ``_REPO_ROOT`` anchor (BOB-062.7a).

When the composition root moved ``app.py`` -> ``bob/runtime/config.py`` the ``__file__``
depth changed (``parents[2]`` -> ``parents[3]``). A wrong depth silently mis-roots the
:class:`PrivacyGuard` — DENYING Bob's whole self-introspection tree and mis-locating the
soul templates — without any test failing on behaviour. This pins the anchor structurally.
"""

from __future__ import annotations

from pathlib import Path

from bob.runtime.config import _DEFAULT_TEMPLATES_DIR, _REPO_ROOT


def test_repo_root_resolves_to_the_actual_repository_root() -> None:
    # ``tests/test_runtime_repo_root.py`` -> ``parents[1]`` is the repo root, resolved the
    # same way ``_REPO_ROOT`` resolves ``.../src/bob/runtime/config.py`` (parents[3]).
    expected = Path(__file__).resolve().parents[1]
    assert expected == _REPO_ROOT


def test_repo_root_points_at_the_project_marker() -> None:
    # The concrete invariant the PrivacyGuard + templates rely on: pyproject.toml is at
    # the anchored root, so ``src``/``tests``/``docs`` resolve against it.
    assert (_REPO_ROOT / "pyproject.toml").is_file()


def test_default_templates_dir_is_under_the_repo_root() -> None:
    assert _DEFAULT_TEMPLATES_DIR == _REPO_ROOT / "bob-soul"
