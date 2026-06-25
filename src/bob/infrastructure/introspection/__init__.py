# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Introspection infrastructure — the subprocess adapter for Bob's self-view.

Realises :class:`bob.domain.ports.RepoIntrospector` over local ``beadloom`` / ``bd``
(a fixed allowlist of read subcommands, via ``create_subprocess_exec`` — never a
shell) and guard-checked file reads. This is the only place the privacy invariant
is enforced at the I/O boundary.
"""

from bob.infrastructure.introspection.subprocess_introspector import (
    DeniedPathError,
    DisallowedCommandError,
    SubprocessRepoIntrospector,
)

__all__ = [
    "DeniedPathError",
    "DisallowedCommandError",
    "SubprocessRepoIntrospector",
]
