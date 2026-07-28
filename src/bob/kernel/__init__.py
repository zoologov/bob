# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel

"""Shared kernel — the infra-neutral contracts every module rests on.

A classical DDD *shared kernel*: the cross-module runtime seams (time, the event
bus, plain LLM completion) and the shared value objects (:data:`LLMMessage`,
:data:`JsonValue`) carried across every module's port bucket. Every module may
import from here (inward-safe, no cycles); the kernel imports from no module.
"""
