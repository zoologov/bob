# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=domain

"""Модуль identity — «кто такой Боб для GitHub и чем он аутентифицируется» (BOB-089).

Фасад bounded context'а: назначение операции → принципал → его реквизиты → короткоживущий
installation-токен, обновляемый ЗАРАНЕЕ. Пакет-СОСЕД модуля ``coding`` — «как Боб пишет
код» и «кем он подписан и что ему разрешено» это разные ответственности; подробности и
рамка — в ``docs/domains/identity/README.md``.
"""

from bob.identity.credentials import AppCredentials, credentials_for
from bob.identity.ports import (
    IdentityConfigError,
    IdentityError,
    InstallationTokenSource,
    Rs256Signer,
    SigningError,
    TokenMintError,
)
from bob.identity.principals import Principal, Purpose, principal_for
from bob.identity.token_lifetime import (
    Freshness,
    InstallationToken,
    parse_expiry,
    token_freshness,
)

__all__ = [
    "AppCredentials",
    "Freshness",
    "IdentityConfigError",
    "IdentityError",
    "InstallationToken",
    "InstallationTokenSource",
    "Principal",
    "Purpose",
    "Rs256Signer",
    "SigningError",
    "TokenMintError",
    "credentials_for",
    "parse_expiry",
    "principal_for",
    "token_freshness",
]
