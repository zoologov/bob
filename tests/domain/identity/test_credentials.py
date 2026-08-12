# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Unit-тесты разбора реквизитов принципала из конфига (BOB-089, срез B).

Ядро отвечает: чем именно аутентифицируется этот принципал и на каком репозитории живёт
его установка. Всё чистое: ни файл ключа не читается, ни сеть не трогается — только
проверка формы и громкий отказ, если конфиг неполон.

🔴 Приватный ключ участвует ПУТЁМ, а не содержимым: содержимое не читается тут вовсе, и
ни одно сообщение об ошибке не имеет права нести секрет. Форму этого пути ядро решает одним
общим правилом (:func:`bob.kernel.config_paths.under_root`) — и решает её ЗДЕСЬ, потому что
«как понимать значение ключа конфига» — это тот же вопрос, что «годно ли оно вообще»
(bob-a6b.15).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bob.identity.credentials import AppCredentials, credentials_for
from bob.identity.ports import IdentityConfigError
from bob.identity.principals import Principal

#: Корень проекта, от которого читается ОТНОСИТЕЛЬНЫЙ путь к ключу (абсолютный — как есть).
_ROOT = Path("/Users/o/bob")

_SECTION = {
    "work_app_id": "4491954",
    "work_app_key": "/Users/o/bob/.secrets/bob-ai-work.private-key.pem",
    "work_repo": "bobiverse-dev/bob",
    "propose_app_id": "4491957",
    "propose_app_key": "/Users/o/bob/.secrets/bob-ai-propose.private-key.pem",
    "propose_repo": "zoologov/bob",
}


def test_each_principal_reads_its_own_three_keys() -> None:
    assert credentials_for(_SECTION, Principal.WORK, root=_ROOT) == AppCredentials(
        app_id="4491954",
        private_key_path="/Users/o/bob/.secrets/bob-ai-work.private-key.pem",
        repository="bobiverse-dev/bob",
    )
    assert credentials_for(_SECTION, Principal.PROPOSE, root=_ROOT) == AppCredentials(
        app_id="4491957",
        private_key_path="/Users/o/bob/.secrets/bob-ai-propose.private-key.pem",
        repository="zoologov/bob",
    )


def test_the_work_principal_never_borrows_the_propose_keys() -> None:
    # Реквизиты не должны «съезжать» между принципалами: у них разные права, и подмена
    # означала бы работу не тем токеном.
    work = credentials_for(_SECTION, Principal.WORK, root=_ROOT)
    assert work.app_id != _SECTION["propose_app_id"]
    assert work.repository != _SECTION["propose_repo"]


@pytest.mark.parametrize("key", ["work_app_id", "work_app_key", "work_repo"])
def test_a_missing_key_is_refused_loudly(key: str) -> None:
    section = {k: v for k, v in _SECTION.items() if k != key}
    with pytest.raises(IdentityConfigError, match=key):
        credentials_for(section, Principal.WORK, root=_ROOT)


@pytest.mark.parametrize("key", ["work_app_id", "work_app_key", "work_repo"])
def test_a_blank_key_is_refused_like_a_missing_one(key: str) -> None:
    # Пустая строка — штатное состояние ненастроенного Боба; молча собрать из неё
    # «реквизиты» значило бы уехать в 401 посреди работы.
    section = {**_SECTION, key: "   "}
    with pytest.raises(IdentityConfigError, match=key):
        credentials_for(section, Principal.WORK, root=_ROOT)


def test_a_non_numeric_app_id_is_refused() -> None:
    # app_id у GitHub App числовой; строка «сходи в другое место» тут — признак того, что
    # в конфиг попало не то значение.
    with pytest.raises(IdentityConfigError, match="work_app_id"):
        credentials_for({**_SECTION, "work_app_id": "bob-ai-work"}, Principal.WORK, root=_ROOT)


@pytest.mark.parametrize(
    "repo",
    [
        "bob",  # без владельца
        "bobiverse-dev/bob/extra",  # лишний сегмент
        "bobiverse-dev/",  # пустое имя
        "/bob",  # пустой владелец
        "bobiverse dev/bob",  # пробел
        "bobiverse-dev/bob?x=1",  # попытка дописать query в путь запроса
        "../../app/installations",  # попытка выйти из своего пути в API
    ],
)
def test_an_unsafe_repository_slug_is_refused(repo: str) -> None:
    # 🔴 Слаг едет в ПУТЬ запроса к api.github.com, поэтому форма проверяется до сети:
    # «owner/repo» из безопасных символов и ничего больше.
    with pytest.raises(IdentityConfigError, match="work_repo"):
        credentials_for({**_SECTION, "work_repo": repo}, Principal.WORK, root=_ROOT)


def test_a_dotted_repository_name_is_accepted() -> None:
    # Точка и подчёркивание в именах репозиториев легальны (``bob.github.io``), поэтому
    # проверка формы не должна их отвергать.
    section = {**_SECTION, "work_repo": "bobiverse-dev/bob.github.io"}
    creds = credentials_for(section, Principal.WORK, root=_ROOT)
    assert creds.repository == "bobiverse-dev/bob.github.io"


def test_a_non_string_value_is_refused_rather_than_coerced() -> None:
    # YAML легко отдаёт int; молча привести его к строке — значит скрыть опечатку.
    with pytest.raises(IdentityConfigError, match="work_app_id"):
        credentials_for({**_SECTION, "work_app_id": 4491954}, Principal.WORK, root=_ROOT)


def test_a_multiline_key_path_is_refused_even_without_a_pem_marker() -> None:
    # Проверка на «это путь, а не ключ» состоит из ДВУХ независимых признаков, и каждый
    # обязан ловить сам по себе: перевод строки в «пути» — уже не путь.
    section = {**_SECTION, "work_app_key": "/repo/.secrets/a.pem\nextra"}
    with pytest.raises(IdentityConfigError, match="work_app_key"):
        credentials_for(section, Principal.WORK, root=_ROOT)


def test_a_single_line_pem_marker_is_refused_too() -> None:
    # …и наоборот: PEM-маркер без перевода строки — тоже не путь.
    section = {**_SECTION, "work_app_key": "-----BEGIN PRIVATE KEY-----"}
    with pytest.raises(IdentityConfigError, match="work_app_key"):
        credentials_for(section, Principal.WORK, root=_ROOT)


def test_the_key_itself_pasted_instead_of_its_path_is_refused() -> None:
    # 🔴 Ключ участвует ПУТЁМ. Если в конфиг попало само PEM-содержимое (простая ошибка
    # копипасты в .env), это надо ронять громко: иначе секрет уехал бы в argv openssl,
    # видимый в ``ps``.
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
    with pytest.raises(IdentityConfigError, match="work_app_key") as excinfo:
        credentials_for({**_SECTION, "work_app_key": pem}, Principal.WORK, root=_ROOT)
    # …и сам секрет в текст отказа не попадает — диагностика по факту, не по значению.
    assert "MIIEow" not in str(excinfo.value)
    assert "PRIVATE KEY" not in str(excinfo.value)
    # Отказ обязан ОБЪЯСНИТЬ, что не так: иначе owner, вставивший ключ вместо пути, увидит
    # только имя ключа конфига и вставит его снова (два мутанта этой фразы выживали, пока
    # тест смотрел лишь на имя ключа).
    assert str(excinfo.value).endswith("not the key material itself (argv is visible in `ps`)")


# --------------------------------------------------------------------------- #
# Форма пути к ключу (bob-a6b.15) — стык «конфиг → openssl» проверен вживую в
# tests/infrastructure/identity/test_key_path_forms_real_openssl.py
# --------------------------------------------------------------------------- #


def test_an_absolute_key_path_outside_the_project_is_kept_as_written() -> None:
    # 🔴 Ключи ЖИВУТ вне дерева репозитория (~/.config/bob/secrets/, 0700/0600 — bob-zmp),
    # значит абсолютная форма это ЕДИНСТВЕННАЯ безопасная, а не экзотика. Приклеенный корень
    # (``/Users/o/bob//Users/o/.config/...``) делал её невыразимой.
    outside = "/Users/o/.config/bob/secrets/bob-ai-work.private-key.pem"

    creds = credentials_for({**_SECTION, "work_app_key": outside}, Principal.WORK, root=_ROOT)

    assert creds.private_key_path == outside


def test_a_relative_key_path_is_read_from_the_project_root() -> None:
    # Совместимость с прежней (небезопасной) формой сохранена — но привязка теперь к КОРНЮ,
    # а не к каталогу, из которого запущен процесс.
    section = {**_SECTION, "work_app_key": ".secrets/bob-ai-work.private-key.pem"}

    creds = credentials_for(section, Principal.WORK, root=_ROOT)

    assert creds.private_key_path == "/Users/o/bob/.secrets/bob-ai-work.private-key.pem"


def test_a_home_relative_key_path_is_not_glued_to_the_project_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Тильда для pathlib не абсолютна, поэтому без раскрытия owner получил бы
    # ``<repo>/~/.config/...`` — тот же дефект другой формой записи.
    monkeypatch.setenv("HOME", "/Users/o")
    section = {**_SECTION, "work_app_key": "~/.config/bob/secrets/work.pem"}

    creds = credentials_for(section, Principal.WORK, root=_ROOT)

    assert creds.private_key_path == "/Users/o/.config/bob/secrets/work.pem"
