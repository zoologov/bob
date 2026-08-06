# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-OPENSSL: КАЖДАЯ форма записи пути к ключу подписывает (bob-a6b.15).

Дефект, из-за которого этот модуль существует, дожил до живого прогона, хотя тестов у
подписи было много: ни один не проходил путь к ключу через РАЗБОР КОНФИГА в форме
«АБСОЛЮТНЫЙ путь ВНЕ дерева репозитория». Все тесты подписи звали ``OpensslRs256Signer``
напрямую, а разбор конфига проверялся на строках, которые никто не пытался открыть — то
есть проверялись две половины, и стык между ними не проверял никто. Owner вынес ключи в
``~/.config/bob/secrets/`` (0700/0600, вне дерева репозитория — bob-zmp), и подпись умерла
на ``/Users/o/bob//Users/o/.config/bob/secrets/bob-ai-work.private-key.pem``.

Поэтому тесты идут ЧЕРЕЗ ПУБЛИЧНЫЙ СТЫК — :func:`bob.identity.credentials.credentials_for`
(разбор конфига) → :class:`~bob.identity.adapters.openssl_signer.OpensslRs256Signer`
(настоящий ``openssl``) → ``openssl dgst -verify`` (вердикт даёт сам openssl) — и покрывают
все три формы значения: абсолютную вне репозитория, домашнюю (``~``) и относительную.

🔴 Ключи Боба в тестах не участвуют: RSA-пара генерируется настоящим ``openssl genrsa`` в
одноразовом каталоге, а ``~/.config/bob/secrets/`` не читается и не трогается вовсе.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bob.identity.adapters.openssl_signer import OpensslRs256Signer
from bob.identity.app_jwt import jwt_claims, signing_input
from bob.identity.credentials import credentials_for
from bob.identity.principals import Principal
from bob.runtime.config import _REPO_ROOT

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="real openssl is not available on this host"
)

_APP_ID = "4491954"


@pytest.fixture
def rsa_keypair(tmp_path: Path) -> tuple[Path, Path]:
    """Одноразовая RSA-пара (приватный, публичный) — настоящим ``openssl genrsa``."""
    private = tmp_path / "keys" / "bob-ai-work.private-key.pem"
    private.parent.mkdir(parents=True, exist_ok=True)
    public = tmp_path / "keys" / "bob-ai-work.public-key.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(private), "2048"], check=True, capture_output=True
    )
    subprocess.run(
        ["openssl", "rsa", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    private.chmod(0o600)
    return private, public


def _section(key_value: str) -> dict[str, object]:
    """Секция конфига ``github`` с ровно одной интересной нам величиной — путём к ключу."""
    return {
        "work_app_id": _APP_ID,
        "work_app_key": key_value,
        "work_repo": "bobiverse-dev/bob",
    }


def _verify(public_key: Path, payload: bytes, signature: bytes, scratch: Path) -> bool:
    """Проверить подпись НАСТОЯЩИМ openssl — вердикт даёт он, а не ассерт теста."""
    signature_file = scratch / "signature.bin"
    signature_file.write_bytes(signature)
    result = subprocess.run(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-verify",
            str(public_key),
            "-signature",
            str(signature_file),
        ],
        input=payload,
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


async def _sign_through_the_config(
    section: dict[str, object], *, root: Path
) -> tuple[bytes, bytes, str]:
    """Пройти путь «конфиг → реквизиты → настоящая подпись» и вернуть (payload, подпись, путь)."""
    credentials = credentials_for(section, Principal.WORK, root=root)
    payload = signing_input(
        jwt_claims(app_id=_APP_ID, now=1_770_000_000, lifetime_seconds=480)
    )
    signature = await OpensslRs256Signer().sign(
        payload, private_key_path=credentials.private_key_path
    )
    return payload, signature, credentials.private_key_path


# --------------------------------------------------------------------------- #
# 🔴 Форма, которой не было ни в одном тесте: АБСОЛЮТНЫЙ путь ВНЕ дерева репозитория
# --------------------------------------------------------------------------- #


async def test_an_absolute_key_path_outside_the_repository_signs(
    rsa_keypair: tuple[Path, Path], tmp_path: Path
) -> None:
    private, public = rsa_keypair
    # Предпосылка теста, а не пожелание: ключ ЛЕЖИТ вне дерева репозитория.
    assert not private.is_relative_to(_REPO_ROOT)

    payload, signature, used_path = await _sign_through_the_config(
        _section(str(private)), root=_REPO_ROOT
    )

    # Путь уехал в openssl ровно тем, чем его написал owner — без корня репозитория спереди.
    assert used_path == str(private)
    assert _verify(public, payload, signature, tmp_path)


async def test_the_repository_root_is_not_glued_onto_an_absolute_key_path(
    rsa_keypair: tuple[Path, Path]
) -> None:
    # Живой отказ выглядел так: '/Users/o/bob//Users/o/.config/bob/secrets/...'. Именно эта
    # склейка и делала безопасную конфигурацию невыразимой.
    private, _ = rsa_keypair

    credentials = credentials_for(_section(str(private)), Principal.WORK, root=_REPO_ROOT)

    assert not credentials.private_key_path.startswith(f"{_REPO_ROOT}{_REPO_ROOT}")
    assert credentials.private_key_path.count(str(_REPO_ROOT)) == 0
    assert Path(credentials.private_key_path).is_file()


async def test_a_home_relative_key_path_signs(
    rsa_keypair: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 🔴 ``~/.config/bob/secrets/...`` — то, как owner называет место ключей. Для pathlib
    # тильда не абсолютна, поэтому без раскрытия она склеилась бы с корнем репозитория.
    private, public = rsa_keypair
    home = tmp_path / "home"
    (home / ".config" / "bob" / "secrets").mkdir(parents=True)
    landed = home / ".config" / "bob" / "secrets" / private.name
    landed.write_bytes(private.read_bytes())
    landed.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))

    payload, signature, used_path = await _sign_through_the_config(
        _section(f"~/.config/bob/secrets/{private.name}"), root=_REPO_ROOT
    )

    assert used_path == str(landed)
    assert _verify(public, payload, signature, tmp_path)


# --------------------------------------------------------------------------- #
# Совместимость: относительная форма продолжает работать — и работает от КОРНЯ
# --------------------------------------------------------------------------- #


async def test_a_relative_key_path_signs_from_the_project_root(
    rsa_keypair: tuple[Path, Path], tmp_path: Path
) -> None:
    private, public = rsa_keypair
    root = tmp_path / "project"
    (root / ".secrets").mkdir(parents=True)
    inside = root / ".secrets" / private.name
    inside.write_bytes(private.read_bytes())
    inside.chmod(0o600)

    payload, signature, used_path = await _sign_through_the_config(
        _section(f".secrets/{private.name}"), root=root
    )

    assert used_path == str(inside)
    assert _verify(public, payload, signature, tmp_path)


async def test_a_relative_key_path_does_not_follow_the_current_directory(
    rsa_keypair: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 🔴 Урок BOB-087.D5b: относительный путь, разрешённый от ``cwd``, зелен в тестах (они
    # стоят в корне) и мёртв в проде, где процесс запущен из другого каталога. Здесь рядом с
    # cwd лежит ОДНОИМЁННЫЙ файл-ловушка, который ключом не является: разрешись путь от cwd —
    # openssl взял бы его и подпись бы не собралась вовсе.
    private, public = rsa_keypair
    root = tmp_path / "project"
    (root / ".secrets").mkdir(parents=True)
    inside = root / ".secrets" / private.name
    inside.write_bytes(private.read_bytes())

    elsewhere = tmp_path / "elsewhere"
    (elsewhere / ".secrets").mkdir(parents=True)
    (elsewhere / ".secrets" / private.name).write_text("не ключ\n", encoding="utf-8")
    monkeypatch.chdir(elsewhere)

    payload, signature, used_path = await _sign_through_the_config(
        _section(f".secrets/{private.name}"), root=root
    )

    assert used_path == str(inside)
    assert _verify(public, payload, signature, tmp_path)
