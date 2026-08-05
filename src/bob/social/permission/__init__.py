# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Permission — чистый домен «Боб спрашивает owner о привилегированном» (BOB-052 .1).

На сообщение НЕ-авторизованного участника, которому нужен инструмент / внутрянка /
owner-данные, Боб заводит pending permission-request и спрашивает owner. Этот пакет —
чистое ядро (без I/O): permission-request (:class:`PermissionRequest`) как immutable
value-object + его состояния (:class:`PermissionState`); семантический privilege-шов
(:class:`PrivilegeNeed` / :class:`PrivilegeContext` / порт :class:`PrivilegeJudge` +
чистый промпт/парсер); NL-предикаты owner-решения (:func:`is_grant` /
:func:`is_deny` / :func:`is_authorize`, консервативные, как BOB-042); и ГОЛОС самой
просьбы (:func:`owner_permission_notice` / :func:`requester_ack`, BOB-090.E) — вердикт
судьи остаётся внутри, наружу идут слова Боба.

Персист — за адаптером ``SqlitePermissionRequestStore``; Tier-0 ``LlmPrivilegeJudge`` и
провязка флоу (.2) / исполнение (.3) строятся поверх.
"""

from __future__ import annotations

from bob.social.permission.entities import PermissionRequest
from bob.social.permission.intent import is_authorize, is_deny, is_grant
from bob.social.permission.privilege import (
    PRIVILEGE_JUDGE_SYSTEM_PROMPT,
    PRIVILEGE_KINDS,
    PrivilegeContext,
    PrivilegeJudge,
    PrivilegeJudgeParseError,
    PrivilegeNeed,
    build_privilege_user_prompt,
    parse_privilege_need,
)
from bob.social.permission.request_voice import owner_permission_notice, requester_ack
from bob.social.permission.state import PermissionState

__all__ = [
    "PRIVILEGE_JUDGE_SYSTEM_PROMPT",
    "PRIVILEGE_KINDS",
    "PermissionRequest",
    "PermissionState",
    "PrivilegeContext",
    "PrivilegeJudge",
    "PrivilegeJudgeParseError",
    "PrivilegeNeed",
    "build_privilege_user_prompt",
    "is_authorize",
    "is_deny",
    "is_grant",
    "owner_permission_notice",
    "parse_privilege_need",
    "requester_ack",
]
