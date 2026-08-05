# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""🔴 REAL-OPENSSL acceptance: подпись App-JWT настоящим инструментом (BOB-089, срез B).

Фейк здесь доказал бы контракт фейка (§0.3 п.4; уроки BOB-084, BOB-087.D5b): подпись — это
поведение НАСТОЯЩЕГО ``openssl`` в подпроцессе, и «мы вернули какие-то байты» ничего не
говорит о том, проверится ли эта подпись. Поэтому тесты:

* генерируют настоящий RSA-ключ в одноразовом каталоге (🔴 НЕ ``.secrets/`` — прод-ключи
  Боба в тестах не участвуют);
* подписывают настоящий ``signing_input`` реальным ``openssl dgst -sha256 -sign``;
* ПРОВЕРЯЮТ подпись обратным вызовом ``openssl dgst -sha256 -verify`` — то есть криптографию
  утверждает сам openssl, а не наш ассерт;
* убеждаются, что подмена одного байта подписи проверку РОНЯЕТ (иначе «проверка» была бы
  вакуумной);
* убеждаются, что приватный ключ едет ПУТЁМ, а не содержимым: содержимое в argv было бы
  видно в ``ps`` любому процессу пользователя.

Skips with a clear reason when ``openssl`` is unavailable.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from bob.identity.adapters import openssl_signer
from bob.identity.adapters.openssl_signer import OpensslRs256Signer
from bob.identity.app_jwt import assemble_jwt, jwt_claims, signing_input
from bob.identity.ports import SigningError

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="real openssl is not available on this host"
)


@pytest.fixture
def rsa_keypair(tmp_path: Path) -> tuple[Path, Path]:
    """Одноразовая RSA-пара в ``tmp_path``: (приватный ключ, публичный ключ)."""
    private = tmp_path / "test-app.private-key.pem"
    public = tmp_path / "test-app.public-key.pem"
    subprocess.run(
        ["openssl", "genrsa", "-out", str(private), "2048"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["openssl", "rsa", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
    )
    return private, public


def _verify(public_key: Path, payload: bytes, signature: bytes, tmp_path: Path) -> bool:
    """Проверить подпись НАСТОЯЩИМ openssl (вердикт даёт он, а не тест)."""
    signature_file = tmp_path / "signature.bin"
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


async def test_the_signature_of_a_real_app_jwt_verifies(
    rsa_keypair: tuple[Path, Path], tmp_path: Path
) -> None:
    private, public = rsa_keypair
    payload = signing_input(jwt_claims(app_id="4491954", now=1_770_000_000, lifetime_seconds=480))
    signature = await OpensslRs256Signer().sign(payload, private_key_path=str(private))
    assert _verify(public, payload, signature, tmp_path)


async def test_a_tampered_signature_fails_verification(
    rsa_keypair: tuple[Path, Path], tmp_path: Path
) -> None:
    # Контроль на вакуумность: если проверка «проходит» и для испорченной подписи, то она
    # ничего не проверяет.
    private, public = rsa_keypair
    payload = signing_input(jwt_claims(app_id="1", now=1_770_000_000, lifetime_seconds=480))
    signature = bytearray(await OpensslRs256Signer().sign(payload, private_key_path=str(private)))
    signature[0] ^= 0xFF
    assert not _verify(public, payload, bytes(signature), tmp_path)


async def test_the_signature_covers_the_payload_not_just_the_key(
    rsa_keypair: tuple[Path, Path], tmp_path: Path
) -> None:
    # Подпись обязана быть подписью ИМЕННО этих байтов: тем же ключом подписанный другой
    # payload не должен проверяться против нашего.
    private, public = rsa_keypair
    mine = signing_input(jwt_claims(app_id="1", now=1_770_000_000, lifetime_seconds=480))
    other = signing_input(jwt_claims(app_id="2", now=1_770_000_000, lifetime_seconds=480))
    signature = await OpensslRs256Signer().sign(other, private_key_path=str(private))
    assert not _verify(public, mine, signature, tmp_path)


async def test_the_assembled_jwt_is_a_three_part_base64url_token(
    rsa_keypair: tuple[Path, Path],
) -> None:
    # Итог всей цепочки — ровно то, что GitHub принимает как Bearer: три base64url-части.
    private, _ = rsa_keypair
    payload = signing_input(jwt_claims(app_id="1", now=1_770_000_000, lifetime_seconds=480))
    signature = await OpensslRs256Signer().sign(payload, private_key_path=str(private))
    token = assemble_jwt(payload, signature)
    header, claims, encoded_signature = token.split(".")
    assert all(part and "=" not in part for part in (header, claims, encoded_signature))
    padded = encoded_signature + "=" * (-len(encoded_signature) % 4)
    assert base64.urlsafe_b64decode(padded.encode("ascii")) == signature


async def test_the_private_key_material_never_enters_the_command_line(
    rsa_keypair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    # 🔴 argv видно в ``ps`` любому процессу пользователя. Ключ участвует ПУТЁМ — здесь это
    # утверждается на РЕАЛЬНОМ прогоне: перехватывается та самая сборка argv, которой
    # подписыватель зовёт openssl, и в ней нет ни маркеров PEM, ни куска ключевого
    # материала.
    private, _ = rsa_keypair
    key_body = private.read_text(encoding="utf-8").replace("\n", "")
    recorded: list[list[str]] = []
    original = openssl_signer.sign_argv

    def _recording(openssl_bin: str, *, private_key_path: str) -> list[str]:
        argv = original(openssl_bin, private_key_path=private_key_path)
        recorded.append(argv)
        return argv

    monkeypatch.setattr(openssl_signer, "sign_argv", _recording)
    payload = signing_input(jwt_claims(app_id="1", now=1_770_000_000, lifetime_seconds=480))
    signature = await OpensslRs256Signer().sign(payload, private_key_path=str(private))

    assert signature  # реальный прогон, а не проверка формы в вакууме
    assert recorded, "подписыватель обошёл сборку argv — тест перестал что-либо проверять"
    argv = recorded[0]
    assert str(private) in argv
    assert all("PRIVATE KEY" not in argument for argument in argv)
    assert not any(len(argument) > 16 and argument in key_body for argument in argv)


async def test_an_unreadable_key_fails_by_type_without_echoing_the_file(
    tmp_path: Path,
) -> None:
    # Диагностика по ТИПУ и по пути, а не по значению: stderr openssl в текст отказа не
    # вкладывается, потому что вкладывать содержимое ключевого материала нельзя ни при
    # каком удобном случае.
    broken = tmp_path / "broken.pem"
    broken.write_text(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAsecret\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    with pytest.raises(SigningError) as excinfo:
        await OpensslRs256Signer().sign(b"payload", private_key_path=str(broken))
    message = str(excinfo.value)
    assert str(broken) in message
    assert "MIIEowIBAAKCAQEAsecret" not in message


async def test_a_missing_key_file_fails_as_a_signing_error(tmp_path: Path) -> None:
    with pytest.raises(SigningError):
        await OpensslRs256Signer().sign(b"payload", private_key_path=str(tmp_path / "nope.pem"))
