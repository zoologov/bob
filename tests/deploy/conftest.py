# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Shared ground for the deploy tests (BOB-116 D8b): a production ``.env`` and its values.

Every value is distinctive, so a test can assert that NONE of them ever reaches the
output of a deploy check — the checks run against the real ``/opt/bob/.env`` and their
output lands in the public GitHub Actions log.
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = REPO_ROOT / "deploy" / "check_config.py"
VPS_CONFIG = REPO_ROOT / "config" / "bob.vps.yaml"

# The eight names the header of config/bob.vps.yaml calls mandatory.
PRODUCTION_ENV: dict[str, str] = {
    "BOB_TELEGRAM__CHAT_ID": "-100777000111",
    "BOB_TELEGRAM__OWNER_ID": "555000222",
    "BOB_TELEGRAM__ALLOWED_CHAT_IDS": "-100777000111,-100777000333",
    "BOB_TELEGRAM__BOB__TOPIC_ID": "4242",
    "BOB_TELEGRAM__TOKEN": "bob-token-SECRET-7f3a",
    "GUPPI_TELEGRAM__TOKEN": "guppi-token-SECRET-91c2",
    "BOB_LLM__TIER0_API_KEY": "tier0-key-SECRET-0d1e",
    "BOB_LLM__TIER1_API_KEY": "tier1-key-SECRET-a5b6",
}


# Stand-ins for the server's commands: each records its call in $STUB_LOG.
STUBS: dict[str, str] = {
    # The remote command string is run by bash locally, stdin (the heredoc) included.
    "ssh": """
while [ $# -gt 0 ]; do
  case "$1" in -i|-o) shift 2 ;; -*) shift ;; *) break ;; esac
done
echo "ssh $1" >> "$STUB_LOG"
shift
exec bash -c "$*"
""",
    # ``bash -lc`` becomes ``bash -c``: a login shell would read the developer's profile
    # and could put a real beadloom/uv ahead of the stubs.
    "sudo": """
echo "sudo $*" >> "$STUB_LOG"
if [ "$1" = "-u" ]; then shift 2; fi
if [ "$1" = "bash" ] && [ "$2" = "-lc" ]; then exec bash -c "$3"; fi
exec "$@"
""",
    "git": 'echo "git $*" >> "$STUB_LOG"\n',
    "uv": 'echo "uv $*" >> "$STUB_LOG"\n',
    "beadloom": 'echo "beadloom $*" >> "$STUB_LOG"\n',
    "sleep": "exit 0\n",
    "systemctl": """
echo "systemctl $*" >> "$STUB_LOG"
if [ "$1" = "is-active" ]; then echo active; fi
""",
    # Copies like install(1); STUB_INSTALL_CORRUPT=1 makes the copy differ from its source.
    "install": """
echo "install $*" >> "$STUB_LOG"
for arg in "$@"; do src="$dst"; dst="$arg"; done
cp -f "$src" "$dst"
if [ "${STUB_INSTALL_CORRUPT:-0}" = "1" ]; then printf 'x' >> "$dst"; fi
""",
    # STUB_OLLAMA_PULL_NOOP=1: the pull "succeeds" but the model never appears in the list.
    "ollama": """
echo "ollama $*" >> "$STUB_LOG"
models="$STUB_STATE/ollama_models"
touch "$models"
case "$1" in
  pull) if [ "${STUB_OLLAMA_PULL_NOOP:-0}" != "1" ]; then echo "$2" >> "$models"; fi ;;
  list)
    echo "NAME ID SIZE MODIFIED"
    while read -r m; do echo "$m abc 5.2GB now"; done < "$models"
    ;;
esac
""",
}


def write_executable(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/bash\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def write_env_file(path: Path, values: dict[str, str]) -> Path:
    """Write ``values`` as a systemd-style environment file (``KEY=VALUE`` per line)."""
    lines = ["# production secrets — test fixture", ""]
    lines += [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def leaked_values(output: str, values: dict[str, str]) -> list[str]:
    """The ``.env`` names whose VALUE appears in ``output`` (must always be empty)."""
    return [key for key, value in values.items() if value and value in output]


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    return write_env_file(tmp_path / ".env", PRODUCTION_ENV)
