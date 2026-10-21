# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Suite-wide pytest plugins.

``real_beadloom`` (BOB-112.11): tests marked ``@pytest.mark.real_beadloom`` drive the real
``beadloom`` binary. With ``BOB_REQUIRE_REAL_BEADLOOM=1`` in the environment — CI sets it on
the Pytest step — any skip of such a test is reported as FAILED with the original skip
reason. Without it (the default, locally) they skip with their reason as before. The
contract and its limits: ``tests/support/real_beadloom_requirement.py``.
"""

pytest_plugins = ("tests.support.real_beadloom_requirement",)
