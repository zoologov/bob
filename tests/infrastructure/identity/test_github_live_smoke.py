# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 ЖИВОЙ READ-ONLY смоук: настоящий GitHub принимает наш App-JWT (BOB-089, срез B).

Зачем он нужен, когда есть тест на настоящем openssl: openssl подтверждает, что подпись
математически верна, но принимает ли эту подпись САМ GitHub — вопрос его верификатора, его
требований к ``iat``/``exp`` и его версии API. Ровно тот класс, где «зелёно на фейке, красно
в проде» и живёт (§0.3 п.4).

Смоук строго READ-ONLY: один ``GET /repos/{repo}/installation``. Токен НЕ минтится, ничего
не создаётся и не пишется.

Он **opt-in**: без явного ``BOB_LIVE_GITHUB_SMOKE=1`` (и без реквизитов в окружении) тест
пропускается с ЯВНОЙ причиной — сеть в обычном прогоне и в CI не трогается, но и не молчит
о том, почему проверка не выполнялась.

Прогон вживую (2026-08-06, dev-волна среза B): оба принципала приняты GitHub'ом, установки
РАЗНЫЕ — ``work`` на форке, ``propose`` на апстриме.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from bob.identity.adapters.github_api import AiohttpGitHubAppApi
from bob.identity.adapters.openssl_signer import OpensslRs256Signer
from bob.identity.app_jwt import assemble_jwt, jwt_claims, signing_input

_OPT_IN = "BOB_LIVE_GITHUB_SMOKE"


def _requirements() -> tuple[str, str, str]:
    """Вернуть ``(app_id, путь к ключу, репозиторий)`` или пропустить с явной причиной."""
    if os.environ.get(_OPT_IN) != "1":
        pytest.skip(f"живой смоук выключен: не задан {_OPT_IN}=1 (сеть не трогаем)")
    app_id = os.environ.get("BOB_GITHUB__PROPOSE_APP_ID", "")
    key_path = os.environ.get("BOB_GITHUB__PROPOSE_APP_KEY", "")
    repository = os.environ.get("BOB_GITHUB__PROPOSE_REPO", "")
    if not (app_id and key_path and repository):
        pytest.skip("живой смоук пропущен: реквизиты принципала propose не заданы в окружении")
    if not Path(key_path).is_file():
        pytest.skip(f"живой смоук пропущен: приватного ключа нет по пути {key_path!r}")
    return app_id, key_path, repository


@pytest.mark.integration
async def test_github_accepts_our_app_jwt_and_names_the_installation() -> None:
    app_id, key_path, repository = _requirements()
    claims = jwt_claims(app_id=app_id, now=int(time.time()), lifetime_seconds=480)
    payload = signing_input(claims)
    signature = await OpensslRs256Signer().sign(payload, private_key_path=key_path)
    app_jwt = assemble_jwt(payload, signature)

    installation = await AiohttpGitHubAppApi().installation_id(
        repository=repository, app_jwt=app_jwt
    )

    # Вердикт даёт GitHub: невалидный JWT вернул бы 401 и TokenMintError.
    assert installation > 0
