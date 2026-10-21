# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Where the real ``beadloom`` is required, a skip of a test that drives it is a failure.

One responsibility: **judge the OUTCOME of a test marked ``real_beadloom``** — not the
preconditions that usually make it run (BOB-112.11, review .9 Major-B).

Why the outcome and not the preconditions. About thirty introspection, diagram and import
parity tests drive the real ``beadloom`` binary and SKIP when it cannot answer: not on PATH,
no index, or a probe call that exits non-zero ("beadloom why unavailable"). The guard of
BOB-112.6 (``tests/test_ci_runs_real_tool_tests.py``) checks the runner's preconditions —
binary on PATH, index present, ``--version`` equals the pin. The review fooled it: the
release 9.0.0 on PATH behind a wrapper whose ``why`` exits 1 — the shape of a CLI that
changed on a version bump. The guard PASSED and the ``why`` test went to SKIP, CI green.
That is the very class BOB-112 exists for, so the verdict has to be taken where the skip
happens: on the test's own report.

The contract:

* ``@pytest.mark.real_beadloom`` on a test says "this test drives the real beadloom binary
  and has nothing else it may legitimately skip on in an environment that requires it".
  A test that ALSO needs a tool CI does not install (``mmdc``, ``bd``) does not carry the
  marker — the marker means the run is mandatory, whatever the reason for the skip. Full git
  history is NOT such a tool: ``ci.yml`` checks out with ``fetch-depth: 0`` (BOB-112.12), so
  the ``diff --since <old commit>`` test IS marked — on the runner a missing commit is a
  broken checkout, not a legitimate skip.
* ``BOB_REQUIRE_REAL_BEADLOOM=1`` (set in ``.github/workflows/ci.yml`` on the Pytest step)
  turns ANY skip of a marked test — ``pytest.skip`` inside it, a ``skipif`` marker, a fixture
  that skips — into a red report that keeps the original skip reason: FAILED for a skip raised
  in the call phase, ERROR for one raised in setup (``skipif``, a skipping fixture) — pytest
  reports a setup-phase refusal as ERROR, and red is red. Unset (or ``0``), nothing changes:
  locally a missing binary is the developer's business and the test SKIPs with its reason.
  Any other value is a usage error: a typo such as ``true`` must not quietly switch the
  requirement off.
* ``xfail`` is not a skip and is left alone.

What it does NOT hold (measured in BOB-112.13):

* a NEW test that drives the real binary but does not carry the marker skips on the runner
  as silently as before — the marker is the declaration; nothing infers it (bead ``bob-xwf``
  is the net: run with a real and with a failing beadloom, require the marker on the
  difference);
* a module-level ``pytest.skip(..., allow_module_level=True)`` in a marked module: the skip
  happens at collection, before ``pytest_runtest_makereport``, and reads «1 skipped», rc 0
  (none of the marked modules does this today — checked by grep, not by a gate);
* a test that returns early instead of skipping passes green, as any vacuous test does.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

MARKER = "real_beadloom"
REQUIRE_ENV = "BOB_REQUIRE_REAL_BEADLOOM"
_ON = "1"
_OFF = frozenset({"", "0"})
FAILURE_PREFIX = "реальный beadloom обязателен в этой среде"
# Read once per session in pytest_configure: the flag cannot change mid-run.
_REQUIRED_KEY = pytest.StashKey[bool]()


def real_beadloom_required(environ: Mapping[str, str]) -> bool:
    """Whether this environment requires the marked tests to run rather than skip."""
    value = environ.get(REQUIRE_ENV, "")
    if value == _ON:
        return True
    if value in _OFF:
        return False
    raise pytest.UsageError(
        f"{REQUIRE_ENV}={value!r}: expected {_ON!r} (required) or unset/'0' (not required)"
    )


def _skip_reason(report: pytest.TestReport) -> str:
    """The reason pytest recorded for a skip (``longrepr`` is ``(path, line, reason)``)."""
    longrepr = report.longrepr
    if isinstance(longrepr, tuple):
        return str(longrepr[2]).removeprefix("Skipped: ")
    return str(longrepr)


def pytest_configure(config: pytest.Config) -> None:
    """Reject a malformed flag before any test runs, not after the first skip."""
    config.stash[_REQUIRED_KEY] = real_beadloom_required(os.environ)


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Turn the skip of a marked test into a failure where the real beadloom is required."""
    del call  # the verdict is read off the report, not the call
    report = yield
    if not item.config.stash.get(_REQUIRED_KEY, False):
        return report
    if item.get_closest_marker(MARKER) is None:
        return report
    if not report.skipped or hasattr(report, "wasxfail"):
        return report
    report.outcome = "failed"
    report.longrepr = f"{FAILURE_PREFIX} ({REQUIRE_ENV}=1): {_skip_reason(report)}"
    return report

