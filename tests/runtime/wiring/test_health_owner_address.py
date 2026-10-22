# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""How Bob addresses the owner in his own signals (BOB-126).

``telegram.owner_address`` («Вова»), else the first word of ``telegram.owner_name``; both
empty — no address at all. What the owner then reads in the DM is held end to end by
``tests/runtime/test_llm_health_composition.py``; here — the edge values of the reading.
"""

from __future__ import annotations

import pytest

from bob.runtime.wiring.health import health_owner_address


@pytest.mark.parametrize(
    ("telegram", "expected"),
    [
        ({"owner_name": "Владимир Зоологов"}, "Владимир"),
        ({"owner_name": "  Владимир   Зоологов  "}, "Владимир"),
        ({"owner_name": "Владимир"}, "Владимир"),
        ({"owner_name": "Владимир Зоологов", "owner_address": "Вова"}, "Вова"),
        ({"owner_name": "", "owner_address": " Вова "}, "Вова"),
        ({"owner_name": "Владимир Зоологов", "owner_address": "   "}, "Владимир"),
        ({"owner_name": "", "owner_address": ""}, None),
        ({"owner_name": "   "}, None),
        ({}, None),
    ],
)
def test_owner_address_falls_back_to_the_first_word_of_the_name(
    telegram: dict[str, object], expected: str | None
) -> None:
    assert health_owner_address({"telegram": telegram}) == expected


def test_no_telegram_section_means_no_address() -> None:
    assert health_owner_address({}) is None
