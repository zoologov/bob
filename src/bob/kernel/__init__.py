# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=kernel

"""Shared kernel — the infra-neutral contracts every module rests on.

A classical DDD *shared kernel*. What it holds (BOB-113 moved here every contract that
two or more modules share, so no type-only import has to point up the module order):

* **runtime seams** (``ports``) — ``Clock``, ``EventBus``/``DomainEvent``, plain LLM
  completion (``LLMProvider``, ``LLMMessage``, ``JsonValue``);
* **memory / reply / tool-calling ports** (``ports``) — ``EpisodeReader``,
  ``MemoryRecall``, ``ReplyGateway``, ``BobUserIdSource``; ``ToolDefinition``,
  ``ToolCall``, ``ToolCallResult``, ``ToolCallingProvider``;
* **intake events** (``events``) — ``MessageReceived``, ``BobMessageReaction``;
* **episode types** (``episode_types``) — ``Recalled``, ``WORK_EVENT_TYPE``;
* **social vocabulary** — ``Interlocutor``/``InterlocutorKind``/``Trust``/``Gender``
  (``interlocutor``), ``Relationship`` (``relationship``), ``RosterMember``
  (``roster``), ``SulkState`` (``sulk``);
* **self-improvement modulators** (``modulators``) — ``RuleModulators``;
* small pure rules several modules ask (``visibility``, ``config_paths``,
  ``poll_backoff``, ``poll_outage``).

Values and contracts only; the BEHAVIOUR stays with its owning module. The rule: the
kernel imports **only the standard library and** ``typing`` — never another ``bob``
module (``tests/domain/kernel/test_kernel_isolation.py`` and the ``kernel-no-*`` lint
rules hold it). Every module may import from here (inward-safe, no cycles).
"""
