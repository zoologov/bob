# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 In CI the tests against the REAL beadloom binary run instead of skipping (BOB-112.6/.11).

About thirty introspection, diagram and tool-health tests drive the real ``beadloom``
binary (``why``/``diff``/``lint``/``sync-check``/``doctor``/``graph``) and SKIP when it is
not on PATH, the repo has no index, or a probe call exits non-zero. ``ci.yml`` ran
``Pytest`` BEFORE installing beadloom, so on the runner every one of them was silently
skipped: the review measured 331 passed / 37 skipped without beadloom on PATH versus
368/368 with the release 9.0.0. The ``why`` / ``diff`` format of the pinned build — the one
``impact_digest``/``health_digest`` were fixed for and the one installed on the VPS — was
never checked by CI, while the run read green.

🔴 Two halves, and only the second one holds the outcome.

1. ``test_ci_runner_has_the_pinned_beadloom_and_its_index_while_pytest_runs`` (BOB-112.6)
   checks PRECONDITIONS on GitHub Actions: the binary is on PATH, the index exists, the
   binary is the build the job declares (``BEADLOOM_VERSION``), and the outcome switch
   ``BOB_REQUIRE_REAL_BEADLOOM=1`` is on. It is an EARLY DIAGNOSTIC that names the missing
   piece — not the verdict. The review of .9 fooled it: the pinned 9.0.0 on PATH behind a
   wrapper whose ``why`` exits 1 — it PASSED while the ``why`` test went to SKIP.
2. The OUTCOME is held by the ``real_beadloom`` marker on each such test plus the hook in
   ``tests/support/real_beadloom_requirement.py``: where ``BOB_REQUIRE_REAL_BEADLOOM=1``
   (CI sets it on the Pytest step) a skip of a marked test is a FAILURE carrying the
   original reason. The tests below prove it on a real inner pytest process — including
   the review's deception, a ``beadloom`` whose every command exits 1.

Outside GitHub Actions the precondition guard SKIPs with a reason saying the runner was NOT
checked — never a green: locally PATH is the developer's business.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.support.real_beadloom_requirement import FAILURE_PREFIX, REQUIRE_ENV

_REPO_ROOT = Path(__file__).resolve().parents[1]
_INDEX = _REPO_ROOT / ".beadloom" / "beadloom.db"
# The job-level variable ci.yml installs beadloom from: one source for the pin and its check.
_PINNED_VERSION_ENV = "BEADLOOM_VERSION"
_VERSION_TIMEOUT_S = 60


def _on_github_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def test_ci_runner_has_the_pinned_beadloom_and_its_index_while_pytest_runs() -> None:
    if not _on_github_actions():
        pytest.skip(
            "not GitHub Actions: whether the runner holds the pinned beadloom and its "
            "index while pytest runs was NOT checked"
        )

    binary = shutil.which("beadloom")
    assert binary is not None, (
        "beadloom is not on PATH while pytest runs, so the real-binary tests skip "
        "silently — install beadloom BEFORE the Pytest step"
    )
    assert _INDEX.exists(), (
        f"no index at {_INDEX}, so the real-binary tests skip as 'repo not indexed' — "
        "run beadloom reindex BEFORE the Pytest step"
    )

    # Read into a local first: a failed assert on ``os.environ.get`` prints the whole
    # environment of the runner into the log.
    required = os.environ.get(REQUIRE_ENV)
    assert required == "1", (
        f"{REQUIRE_ENV} is not '1' on the Pytest step: a skip of a real_beadloom test would "
        "pass as a quiet skip — the outcome of those tests is not held"
    )

    pinned = os.environ.get(_PINNED_VERSION_ENV, "")
    assert pinned, f"the job declares no {_PINNED_VERSION_ENV}: nothing to check the build against"

    proc = subprocess.run(  # noqa: S603 — the binary PATH resolved above, fixed argv
        [binary, "--version"],
        capture_output=True,
        text=True,
        timeout=_VERSION_TIMEOUT_S,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    words = proc.stdout.split()
    reported = words[-1] if words else ""
    assert reported == pinned, (
        f"beadloom on PATH reports {reported!r} but the job pins {pinned!r}: the real-binary "
        "tests would check another build"
    )


# --- 🔴 BOB-112.11: the OUTCOME of the real-binary tests, not their preconditions --------
#
# Everything below runs a REAL inner pytest process — the plugin as the suite loads it, not
# a call into its functions. The inner outcome is read off the reports pytest itself logs
# (``pytest_runtest_logreport``: the final report, the one the exit status counts), not off
# a JUnit file: JUnit files a FAILED xfail-marked test under <skipped>, and that is exactly
# the confusion between "skipped" and "failed" this module exists to rule out.

_PLUGIN = "tests.support.real_beadloom_requirement"
_INNER_TIMEOUT_S = 300
_IMPACT_TEST = (
    "tests/infrastructure/introspection/test_subprocess_introspector_integration.py"
    "::test_impact_of_a_real_node_is_condensed_not_a_screenshot"
)
# A PATH with the system tools and nothing the developer installed (no uv tool, no brew).
_BARE_PATH = os.pathsep.join(("/usr/bin", "/bin"))
_RECORDER = "bob_inner_outcome_recorder"
_RECORD_ENV = "BOB_INNER_OUTCOME_RECORD"
_RECORDER_SOURCE = f"""
import json, os

def pytest_runtest_logreport(report):
    with open(os.environ[{_RECORD_ENV!r}], "a", encoding="utf-8") as sink:
        sink.write(json.dumps({{
            "name": report.nodeid.rsplit("::", 1)[-1],
            "outcome": report.outcome,
            "xfail": hasattr(report, "wasxfail"),
            "text": report.longreprtext,
        }}) + "\\n")
"""


@dataclass(frozen=True)
class _Outcome:
    status: str  # "passed" | "failed" | "skipped" | "xfailed"
    message: str


def _fold(records: list[dict[str, object]]) -> dict[str, _Outcome]:
    """Fold the per-phase reports into one outcome per test: failed > skipped > passed."""
    rank = {"passed": 0, "xfailed": 1, "skipped": 1, "failed": 2}
    outcomes: dict[str, _Outcome] = {}
    for record in records:
        status = str(record["outcome"])
        if status == "skipped" and record["xfail"]:
            status = "xfailed"
        name = str(record["name"])
        seen = outcomes.get(name)
        if seen is None or rank[status] > rank[seen.status]:
            outcomes[name] = _Outcome(status, str(record["text"]))
    return outcomes


def _run_inner(
    tmp_path: Path, args: list[str], *, require: str | None, path: str | None = None
) -> tuple[int, dict[str, _Outcome]]:
    """Run pytest in a subprocess and return its exit code and per-test outcomes."""
    recorder_dir = tmp_path / "recorder"
    recorder_dir.mkdir(exist_ok=True)
    (recorder_dir / f"{_RECORDER}.py").write_text(_RECORDER_SOURCE, encoding="utf-8")
    record = tmp_path / "inner-outcomes.jsonl"
    record.unlink(missing_ok=True)
    env = dict(os.environ)
    env.pop(REQUIRE_ENV, None)
    if require is not None:
        env[REQUIRE_ENV] = require
    if path is not None:
        env["PATH"] = path
    env[_RECORD_ENV] = str(record)
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(_REPO_ROOT), str(recorder_dir), env.get("PYTHONPATH")))
    )
    proc = subprocess.run(  # noqa: S603 — this interpreter, fixed argv
        [
            sys.executable, "-m", "pytest", "-p", _PLUGIN, "-p", _RECORDER,
            "-p", "no:randomly", "-p", "no:cacheprovider", "-q", *args,
        ],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=_INNER_TIMEOUT_S,
        check=False,
    )
    if not record.exists():
        return proc.returncode, {}
    lines = record.read_text(encoding="utf-8").splitlines()
    return proc.returncode, _fold([json.loads(line) for line in lines])


def _write_inner_tests(tmp_path: Path) -> Path:
    module = tmp_path / "inner" / "test_inner.py"
    module.parent.mkdir()
    module.write_text(_INNER_TESTS, encoding="utf-8")
    return module


_INNER_TESTS = '''
import pytest

@pytest.mark.real_beadloom
def test_marked_skip_inside():
    pytest.skip("beadloom why unavailable")

@pytest.mark.real_beadloom
@pytest.mark.skipif(True, reason="beadloom not on PATH")
def test_marked_skipif():
    pass

@pytest.mark.real_beadloom
def test_marked_pass():
    assert True

@pytest.mark.real_beadloom
@pytest.mark.xfail(reason="known", strict=True)
def test_marked_xfail():
    raise AssertionError

def test_unmarked_skip():
    pytest.skip("live smoke off")
'''


def test_where_required_every_skip_of_a_marked_test_fails_with_its_original_reason(
    tmp_path: Path,
) -> None:
    module = _write_inner_tests(tmp_path)

    rc, out = _run_inner(tmp_path, [str(module)], require="1")

    assert set(out) == {
        "test_marked_skip_inside", "test_marked_skipif", "test_marked_pass",
        "test_marked_xfail", "test_unmarked_skip",
    }, f"inner harness broken: collected {sorted(out)}"
    assert rc == 1
    assert out["test_marked_skip_inside"].status == "failed"
    assert FAILURE_PREFIX in out["test_marked_skip_inside"].message
    assert "beadloom why unavailable" in out["test_marked_skip_inside"].message
    assert out["test_marked_skipif"].status == "failed"
    assert "beadloom not on PATH" in out["test_marked_skipif"].message
    assert out["test_marked_pass"].status == "passed"
    assert out["test_marked_xfail"].status == "xfailed", "xfail is not a skip"
    assert out["test_unmarked_skip"].status == "skipped", "an unmarked skip is untouched"


@pytest.mark.parametrize("require", [None, "0", ""])
def test_where_not_required_a_marked_test_skips_with_its_reason(
    tmp_path: Path, require: str | None
) -> None:
    module = _write_inner_tests(tmp_path)

    rc, out = _run_inner(tmp_path, [str(module)], require=require)

    assert rc == 0
    assert len(out) == 5, f"inner harness broken: collected {sorted(out)}"
    assert out["test_marked_skip_inside"].status == "skipped"
    assert "beadloom why unavailable" in out["test_marked_skip_inside"].message
    assert out["test_marked_skipif"].status == "skipped"


def test_a_malformed_flag_is_a_usage_error_not_a_quiet_off(tmp_path: Path) -> None:
    module = _write_inner_tests(tmp_path)

    rc, out = _run_inner(tmp_path, [str(module)], require="true")

    assert rc == pytest.ExitCode.USAGE_ERROR
    assert out == {}


def _failing_beadloom(tmp_path: Path) -> str:
    """A PATH whose ``beadloom`` answers every command with rc 1 — a changed CLI."""
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    fake = bin_dir / "beadloom"
    fake.write_text("#!/bin/sh\necho 'no such command' >&2\nexit 1\n", encoding="utf-8")
    fake.chmod(0o755)
    return os.pathsep.join((str(bin_dir), _BARE_PATH))


def test_the_real_why_test_fails_where_required_when_the_binary_cannot_answer(
    tmp_path: Path,
) -> None:
    """🔴 The review's deception, on the real test: a beadloom whose ``why`` exits 1.

    Required → the real ``why`` test FAILS with its own skip reason; not required → it
    SKIPS as before. The binary here is a stand-in, so this runs on any machine.
    """
    path = _failing_beadloom(tmp_path)

    rc_required, required = _run_inner(tmp_path, [_IMPACT_TEST], require="1", path=path)
    rc_free, free = _run_inner(tmp_path, [_IMPACT_TEST], require=None, path=path)

    name = _IMPACT_TEST.rsplit("::", 1)[1]
    assert set(required) == {name} == set(free), "inner harness broken: wrong collection"
    assert rc_required == 1
    assert required[name].status == "failed"
    assert FAILURE_PREFIX in required[name].message
    assert "beadloom why unavailable" in required[name].message
    assert rc_free == 0
    assert free[name].status == "skipped"


def test_the_real_why_test_fails_where_required_when_beadloom_is_not_on_path(
    tmp_path: Path,
) -> None:
    assert shutil.which("beadloom", path=_BARE_PATH) is None, "precondition: no beadloom"

    rc, out = _run_inner(tmp_path, [_IMPACT_TEST], require="1", path=_BARE_PATH)

    name = _IMPACT_TEST.rsplit("::", 1)[1]
    assert set(out) == {name}, "inner harness broken: wrong collection"
    assert rc == 1
    assert out[name].status == "failed"
    assert FAILURE_PREFIX in out[name].message
