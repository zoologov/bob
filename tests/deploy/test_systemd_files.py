# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The environment the two tracked systemd files give their processes (BOB-126).

``deploy/bob.service`` sets the process time zone: the VPS runs in Asia/Kolkata and the
owner lives in Moscow, so Bob's texts said «+05:30» (bob-ol3). The test reads the
``Environment=`` lines of the unit the way systemd hands them to the process and runs
Bob's own time code (:mod:`bob.kernel.local_time`) in a child process with exactly that
environment: the observable is the offset Bob prints, not the line in the file.

The unit also orders Bob after Ollama and pulls it in: the very first thing Bob's startup
does is ask the understudy's endpoint for its models, and after a VPS reboot that question
must not reach a port nobody listens on yet — the understudy would then be stood down until
the next restart. The embedder lives on the same Ollama.

``deploy/ollama-keep-alive.conf`` is a drop-in for ``ollama.service``: it must be a
``[Service]`` section that keeps models loaded forever and allows two of them at most.

Not held here: systemd itself (``systemd-analyze verify`` is not on every host) — that the
deploy INSTALLS both files is held by ``test_deploy_workflow.py`` and ``test_bootstrap.py``.
"""

from __future__ import annotations

import os
import subprocess
import sys

from tests.deploy.conftest import REPO_ROOT

_UNIT = REPO_ROOT / "deploy" / "bob.service"
_KEEP_ALIVE = REPO_ROOT / "deploy" / "ollama-keep-alive.conf"
_TIMEOUT_S = 30
# The VPS's own zone (bob-ol3). The child starts in it, like Bob on the server, and the
# unit's environment goes on top — a developer's host zone must not decide the result
# (on a host in Moscow a unit without TZ printed «+03:00» too: measured, BOB-126).
_SERVER_ZONE = "Asia/Kolkata"

# 2026-10-01 06:10 UTC, the way Bob's clock reports a moment; printed in the process zone.
_PRINT_OFFSET = (
    "from datetime import UTC, datetime\n"
    "from bob.kernel.local_time import in_local_zone, utc_offset_label\n"
    "print(utc_offset_label(in_local_zone(datetime(2026, 10, 1, 6, 10, tzinfo=UTC))))\n"
)


def _unit_directive(text: str, name: str) -> list[str]:
    """Every unit listed by ``name=`` lines of the ``[Unit]`` section, as systemd merges them."""
    units: list[str] = []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section == "[Unit]" and line.startswith(f"{name}="):
            units += line.removeprefix(f"{name}=").split()
    return units


def _service_environment(text: str) -> dict[str, str]:
    """``Environment=KEY=VALUE`` lines of the ``[Service]`` section, as systemd passes them."""
    environment: dict[str, str] = {}
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line
            continue
        if section == "[Service]" and line.startswith("Environment="):
            key, _, value = line.removeprefix("Environment=").partition("=")
            environment[key] = value
    return environment


def _offset_under(environment: dict[str, str]) -> str:
    """The UTC offset Bob prints on the server when started with ``environment``."""
    result = subprocess.run(  # noqa: S603 — the test's own interpreter, a fixed script
        [sys.executable, "-c", _PRINT_OFFSET],
        capture_output=True,
        text=True,
        env={**os.environ, "TZ": _SERVER_ZONE, **environment},
        timeout=_TIMEOUT_S,
        check=True,
    )
    return result.stdout.strip()


def test_bobs_unit_makes_his_texts_speak_moscow_time() -> None:
    environment = _service_environment(_UNIT.read_text(encoding="utf-8"))

    assert _offset_under(environment) == "+03:00"


def test_without_the_unit_bob_speaks_the_servers_zone() -> None:
    # The baseline the test above departs from: no TZ from the unit — the server's +05:30.
    assert _offset_under({}) == "+05:30"


def test_the_keep_alive_drop_in_keeps_two_models_loaded_forever() -> None:
    environment = _service_environment(_KEEP_ALIVE.read_text(encoding="utf-8"))

    assert environment == {"OLLAMA_KEEP_ALIVE": "-1", "OLLAMA_MAX_LOADED_MODELS": "2"}


def test_bob_starts_after_ollama_and_pulls_it_in() -> None:
    text = _UNIT.read_text(encoding="utf-8")

    assert "ollama.service" in _unit_directive(text, "After")
    assert "ollama.service" in _unit_directive(text, "Wants")


def test_bob_still_waits_for_the_network() -> None:
    # Adding Ollama must not drop the ordering Bob had: Telegram and the cloud need the network.
    text = _UNIT.read_text(encoding="utf-8")

    assert "network-online.target" in _unit_directive(text, "After")
    assert "network-online.target" in _unit_directive(text, "Wants")


def test_bob_does_not_die_or_refuse_to_start_with_ollama() -> None:
    # Wants=, never a hard tie: without Ollama Bob starts and says the understudy is gone,
    # and stopping or failing Ollama must not stop Bob (review m3).
    text = _UNIT.read_text(encoding="utf-8")

    for hard_tie in ("Requires", "Requisite", "BindsTo", "PartOf"):
        assert "ollama.service" not in _unit_directive(text, hard_tie), hard_tie
