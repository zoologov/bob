# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Decisions the owner took for production hold in the tracked config (BOB-116).

``config/bob.vps.yaml`` REPLACES the hand-written production config on every deploy, so a
setting production had and the tracked file lacks silently falls back to its default. Each
test here pins one value read on the VPS and decided by the owner, loaded the way Bob
loads it: through the real loader with the production ``.env`` names.
"""

from __future__ import annotations

from bob.infrastructure.config.loader import ConfigLoader
from bob.infrastructure.llm.factory import understudy_endpoint
from tests.deploy.conftest import PRODUCTION_ENV, VPS_CONFIG


def test_the_autobiography_stays_on_in_production() -> None:
    # Q5 RFC BOB-116: memory.autobiography was true on the VPS (read 2026-10-21). Without it
    # the deploy turns the autobiography off, and the outage episode «я молчал» that the
    # live smoke (deploy/RUNBOOK.md §10.2) expects is never written.
    config = ConfigLoader(yaml_path=VPS_CONFIG, env=PRODUCTION_ENV).load()

    assert config["memory"].get("autobiography") is True


def test_the_tier0_understudy_is_on_with_qwen35_4b_on_the_local_ollama() -> None:
    # BOB-126: the owner's decision on the BOB-123 measurement (2026-10-22) — the Tier-0
    # understudy is on in production, qwen3.5:4b (3.1 GB) next to bge-m3 (1.2 GB). Decided
    # by the same understudy_endpoint the provider factory and deploy step 4/4 use.
    config = ConfigLoader(yaml_path=VPS_CONFIG, env=PRODUCTION_ENV).load()

    endpoint = understudy_endpoint(config)

    assert endpoint is not None
    assert endpoint.model == "qwen3.5:4b"
    assert endpoint.base_url == "http://localhost:11434/v1"
