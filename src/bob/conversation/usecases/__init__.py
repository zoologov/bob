# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""Conversation use-cases — orchestration of Bob's turn decisions over ports.

The response decision (:mod:`~bob.conversation.usecases.decide_response`): whether and
how much Bob engages with a turn. Depends on the conversation domain (through ports)
and reads personality expression VOs; never on infrastructure directly.
"""
