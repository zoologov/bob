# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=identity
# beadloom:layer=infrastructure

"""OpensslRs256Signer — подпись App-JWT настоящим ``openssl`` (BOB-089, срез B).

Реализует :class:`bob.identity.ports.Rs256Signer`. Одна ответственность: превратить байты
``header.payload`` в RS256-подпись.

🔴 ПОЧЕМУ ``openssl``, А НЕ БИБЛИОТЕКА. В зависимостях Боба нет ни PyJWT, ни
``cryptography``, а тянуть их ради одной подписи — плата за всю поверхность транзитивных
зависимостей в проекте, где креды и так самое чувствительное место. ``openssl dgst -sha256
-sign`` — проверенный путь (им координатор подписывал JWT вживую при настройке доступов),
и он уже есть на любой машине, где живёт git.

🔴 ЧТО ЕДЕТ, А ЧТО НЕТ. Ключ передаётся ПУТЁМ: содержимое в argv было бы видно в ``ps``
любому процессу пользователя. Подписываемые байты уходят в **stdin**, подпись приходит из
stdout сырыми байтами (без ``-out``: временный файл с подписью — лишняя вещь на диске).
Шелла нет вовсе (``create_subprocess_exec``), поэтому интерполировать в него нечего.

🔴 ДИАГНОСТИКА ПО ТИПУ, А НЕ ПО ЗНАЧЕНИЮ. При сбое в текст ошибки идут шаг, путь к ключу и
код возврата — но НЕ stderr openssl и не байты payload'а: класть рядом с ключевым
материалом ленту вывода, происхождение которой мы не контролируем, — ровно та привычка, из
которой берутся утечки. Кода возврата и пути достаточно, чтобы отличить «файла нет» от
«ключ зашифрован/не RSA» (проверяется в тесте на настоящем openssl).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from bob.identity.ports import SigningError

__all__ = ["OpensslRs256Signer", "sign_argv"]

logger = logging.getLogger(__name__)

#: Подпись — операция на доли секунды; больше секунд ждать нечего (защита от зависания).
_DEFAULT_TIMEOUT_SECONDS = 10.0


def sign_argv(openssl_bin: str, *, private_key_path: str) -> list[str]:
    """Собрать фиксированную argv подписи: ключ — ПУТЁМ, данные придут в stdin."""
    return [openssl_bin, "dgst", "-sha256", "-sign", private_key_path]


class OpensslRs256Signer:
    """Подписыватель RS256 через подпроцесс ``openssl`` (без шелла, ключ путём)."""

    def __init__(
        self,
        *,
        openssl_bin: str = "openssl",
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._openssl_bin = openssl_bin
        self._timeout = timeout_seconds

    async def sign(self, payload: bytes, *, private_key_path: str) -> bytes:
        """Вернуть RS256-подпись ``payload`` ключом по пути ``private_key_path``."""
        argv = sign_argv(self._openssl_bin, private_key_path=private_key_path)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise SigningError(
                f"could not run {self._openssl_bin!r} to sign the App JWT"
            ) from exc
        signature = await self._communicate(process, payload, private_key_path)
        if not signature:
            raise SigningError(
                f"{self._openssl_bin!r} produced an empty signature for the key at "
                f"{private_key_path!r}"
            )
        logger.debug("App JWT signed with the key at %s", private_key_path)
        return signature

    async def _communicate(
        self, process: asyncio.subprocess.Process, payload: bytes, private_key_path: str
    ) -> bytes:
        """Прокачать ``payload`` через процесс и вернуть подпись (или отказать по типу)."""
        try:
            out, _ = await asyncio.wait_for(process.communicate(payload), timeout=self._timeout)
        except TimeoutError as exc:
            process.kill()
            await _reap(process)
            raise SigningError(
                f"signing the App JWT timed out after {self._timeout:g}s"
            ) from exc
        if process.returncode != 0:
            raise SigningError(
                f"{self._openssl_bin!r} could not sign with the key at {private_key_path!r} "
                f"(exit code {process.returncode}); the file is missing, unreadable, "
                "passphrase-protected or not an RSA key"
            )
        return out


async def _reap(process: asyncio.subprocess.Process) -> None:
    """Дожать убитый процесс, чтобы не оставить зомби."""
    with contextlib.suppress(ProcessLookupError):
        await process.wait()
