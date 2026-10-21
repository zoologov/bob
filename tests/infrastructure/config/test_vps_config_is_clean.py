# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Guard: the tracked production config carries no secrets and no identifiers (BOB-116).

``config/bob.vps.yaml`` is the production config, tracked so that «the effective config
on the VPS = the repository» can be checked by the deploy. The repository is PUBLIC, so
the file must hold neither a secret (token, key) nor an identifier (chat, owner, topic
ids, the owner's name): those live in ``/opt/bob/.env`` and reach the config through
the loader's env layer, typed like their defaults.

The guard reads the file three ways, because each catches what the others cannot:

1. **Parsed keys.** Every key whose name carries a sensitive marker has no value.
2. **Digit runs.** No run of six or more digits anywhere in the text — comments
   included, and with separators between digits removed first (``_``, ``-``, ``.``,
   spaces, a tab, a non-breaking space, any number and mix of them), so
   ``-100_123_456``, ``-100 4372 9473 07``, ``-100-4372-9473-07`` and
   ``-100.4372.9473.07`` are still one run each; a calendar date ``20YY-MM-DD`` breaks a
   run instead of joining it (the rule and its named cost are in the helper's docstring).
   A Telegram user id has at least six
   digits and a group id thirteen; no legitimate setting needs that many except the log
   rotation size, and that one exemption is narrow: only the VALUE of
   ``runtime.log_max_bytes`` on its own line is skipped, so an id in a trailing comment
   on that same line is still a finding. The scan is the same one the example-config
   guard runs (:mod:`tests.support.id_like_numbers`): BOB-116 D8b found an id split by
   spaces that this guard, then joining ``_`` only, let through, and the BOB-116 review
   (m3) found one split by hyphens or dots that the next version let through.
3. **The real loader.** The tracked file loaded with the ``.env`` names the header
   lists yields typed ids — the header is not prose but a working contract.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import yaml

from bob.infrastructure.config.loader import ConfigLoader
from tests.support.id_like_numbers import has_log_rotation_value, id_like_digit_runs
from tests.support.repository_root import repository_root

_VPS_CONFIG = repository_root() / "config" / "bob.vps.yaml"

# A key whose name contains any of these must have no value in the tracked file.
_SENSITIVE_MARKERS = (
    "token",
    "key",
    "chat_id",
    "owner_id",
    "topic_id",
    "allowed_chat_ids",
    "owner_dm_chat_id",
    "owner_name",
)

# The names the header of the tracked file tells the owner to keep in /opt/bob/.env.
_ID_ENV = {
    "BOB_TELEGRAM__OWNER_ID": "123",
    "BOB_TELEGRAM__CHAT_ID": "-100",
    "BOB_TELEGRAM__ALLOWED_CHAT_IDS": "-100,-200",
    "BOB_TELEGRAM__BOB__TOPIC_ID": "32",
}
_FAKE_SECRET = "not-a-secret"  # noqa: S105 — test fixture, not a credential
_SECRET_ENV = {
    "BOB_TELEGRAM__TOKEN": _FAKE_SECRET,
    "GUPPI_TELEGRAM__TOKEN": _FAKE_SECRET,
    "BOB_LLM__TIER0_API_KEY": _FAKE_SECRET,
    "BOB_LLM__TIER1_API_KEY": _FAKE_SECRET,
}


def _items(node: Any, prefix: str = "") -> Iterator[tuple[str, str, Any]]:
    """Yield ``(dotted_path, key, value)`` for every mapping entry, depth-first."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield path, str(key), value
            yield from _items(value, path)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _items(item, f"{prefix}[{index}]")


def _is_empty(value: Any) -> bool:
    return value is None or value in ("", [], {})


def _text() -> str:
    return _VPS_CONFIG.read_text(encoding="utf-8")


def test_the_tracked_vps_config_exists() -> None:
    assert _VPS_CONFIG.is_file(), f"{_VPS_CONFIG} is the tracked production config"


def test_no_sensitive_key_carries_a_value() -> None:
    parsed = yaml.safe_load(_text())

    findings = [
        f"{path} = {value!r}"
        for path, key, value in _items(parsed)
        if any(marker in key for marker in _SENSITIVE_MARKERS) and not _is_empty(value)
    ]

    assert findings == [], f"secrets/ids belong in /opt/bob/.env, not here: {findings}"


def test_no_id_like_digit_run_anywhere_in_the_text() -> None:
    findings = [f"line {run.line}: {run.digits}" for run in id_like_digit_runs(_text())]

    assert findings == [], f"an id-like number (6+ digits) in the tracked config: {findings}"


def test_the_log_rotation_exemption_still_applies_to_its_value() -> None:
    # The exemption is part of the rule; if the key moved or vanished, say so here
    # instead of letting the digit-run test pass on a file that no longer has it.
    assert has_log_rotation_value(_text())


def test_ids_from_env_load_typed_over_the_tracked_file() -> None:
    config = ConfigLoader(yaml_path=_VPS_CONFIG, env={**_ID_ENV, **_SECRET_ENV}).load()
    telegram = config["telegram"]

    assert telegram["owner_id"] == 123
    assert type(telegram["owner_id"]) is int
    assert telegram["chat_id"] == -100
    assert type(telegram["chat_id"]) is int
    assert telegram["allowed_chat_ids"] == [-100, -200]
    assert telegram["bob"]["topic_id"] == 32
    assert type(telegram["bob"]["topic_id"]) is int
    assert telegram["bob"]["token"] == _FAKE_SECRET
    assert telegram["guppi"]["token"] == _FAKE_SECRET
    assert config["llm"]["tier0_api_key"] == _FAKE_SECRET
    assert config["llm"]["tier1_api_key"] == _FAKE_SECRET


def test_the_header_names_every_env_variable_the_loader_test_feeds() -> None:
    header = "\n".join(line for line in _text().splitlines() if line.startswith("#"))

    missing = [name for name in (*_ID_ENV, *_SECRET_ENV) if name not in header]

    assert missing == [], f"the header must tell the owner to set: {missing}"
