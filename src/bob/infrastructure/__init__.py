# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Infrastructure layer — adapters that realise the domain ports.

Telegram / LLM / SQLite / config live here. Adapters depend inward (on the domain
ports and :mod:`bob.application`); nothing in the domain or
application imports this package — wiring happens only in ``bob.app``.
"""
