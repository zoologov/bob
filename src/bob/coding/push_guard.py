# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Окружение спавна claude: барьер push'а + изоляция кредов (BOB-087.E/bob-5ao, BOB-089.C).

ОДНА ответственность: собрать окружение процесса ``claude`` — ЕДИНСТВЕННЫЙ шов, через
который спавн получает свой git. Обе меры выражаются одним и тем же блоком
``GIT_CONFIG_COUNT`` / ``GIT_CONFIG_KEY_i`` / ``GIT_CONFIG_VALUE_i`` (env-конфиг читается
git'ом ПОСЛЕДНИМ и наследуется всеми дочерними процессами), поэтому второго механизма
рядом нет и быть не должно: он неизбежно разошёлся бы с этим по нумерации пар.

1. **Барьер push'а** (bob-5ao) — набор ``url.<заглушка>.pushInsteadOf = <префикс>``: git
   переписывает push-URL, начинающийся с префикса, в заглушку, и вызов умирает на
   ``remote helper '<схема>'``. Fetch/clone не затрагиваются: правится ТОЛЬКО push
   (``pushInsteadOf``, не ``insteadOf``).
2. **Изоляция кредов** (BOB-089, срез C) — спавн перестаёт видеть credential helper
   owner'а: решения в чистом ядре :mod:`bob.identity.spawn_isolation`, здесь только
   склейка. 🔴 Одного барьера было недостаточно ровно потому, что креды оставались на
   месте: сетевая дорога к апстриму была жива, барьер лишь мешал по ней пойти нечаянно.

🔴 ЧЕСТНО О СИЛЕ МЕРЫ (проверено на реальном git 2.49 — bob-5ao). Это СТРАХОВКА ОТ
НЕЧАЯННОГО push, а НЕ граница и НЕ восстановление структурности INV-2. Процесс под
``bypassPermissions`` работает под тем же UID и владеет собственным окружением, поэтому
``GIT_CONFIG_COUNT=0 git push …`` (или ``env -u``) снимает барьер одной командой; ещё один
проверенный обход — ``git remote set-url --push`` (явный ``pushurl`` по документации git
отменяет ``pushInsteadOf``). И совсем мимо push: linked worktree делит ``.git`` с основным
репозиторием, так что ``git update-ref refs/heads/main <sha>`` двигает main ЛОКАЛЬНО
(проверено: проходит, основной чекаут видит сдвиг), а ``gh pr merge`` идёт через API
gh-токена. Структурными эти классы делает только другой принципал (контейнер/отдельный
UID с собственными кредами) либо серверная защита ветки — не конфиг git.

Почему тогда мера всё же есть: самый вероятный реальный инцидент — не злоумышленник, а
модель, которая «доделала задачу» и выполняет ``git push``. Такой push теперь падает
громко и с самообъясняющей ошибкой. Барьер применяется РОВНО при owner-ослаблении
(``coder.allow_bypass``); при выключенном флаге вердикт — ``None``, то есть спавн вообще
без ``env=`` и байт-в-байт прежний.

Почему НЕ ``remote.origin.pushurl`` (первичное предложение среза D5b): проверено, что этот
ключ МНОГОЗНАЧНЫЙ — env-значение не замещает файловое, а добавляется, и git пушит во все
URL сразу (ref уезжает в реальный origin, а на экране печатается ``fatal`` про заглушку),
плюс наличие ``pushurl`` отключает ``pushInsteadOf``. То есть заглушка через ``pushurl``
строго слабее выбранной и ещё и маскирует исход.

🔴 ЧТО МЕНЯЕТ СРЕЗ C, А ЧТО НЕТ. Изоляция окружением — тоже НЕ граница (тот же UID, то же
владение своим окружением: ``env -u GIT_CONFIG_NOSYSTEM``, ``GIT_CONFIG_COUNT=0``, и сам
логин-keychain остаётся читаемым). Меняется другое: обход перестаёт что-либо давать.
Дотянуться можно только до кредов, у которых НЕТ права записи в апстрим (срез B), а
локальный ``update-ref`` до main owner'а больше не достаёт, потому что ``.git`` у клона
свой (срез A). Структурными остаются ровно эти два свойства — не конфиг git.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.identity.spawn_isolation import (
    OWNER_CREDENTIAL_VARS,
    isolation_config_pairs,
    isolation_env,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.identity.spawn_isolation import SpawnIsolation

__all__ = [
    "PUSH_GUARD_STUB_URL",
    "PUSH_GUARD_URL_PREFIXES",
    "guarded_spawn_env",
]

#: URL-заглушка, в которую переписывается любой push. Схема (до ``://``) намеренно
#: читаема: git печатает ``remote helper 'bob-push-blocked' aborted session``, и это
#: сообщение само объясняет, почему push не прошёл.
PUSH_GUARD_STUB_URL = "bob-push-blocked://main-only-through-a-pr/"

#: Префиксы push-URL, которые перехватываются. Покрыты все транспорты, которыми можно
#: дотянуться до удалённого репозитория, включая scp-подобный ``git@host:path`` (прод-origin
#: Боба именно такой) и ``file://``. Голый локальный путь (``../other-clone``) НЕ покрыт —
#: префиксом он не выражается; до main на сервере он и не ведёт.
PUSH_GUARD_URL_PREFIXES: tuple[str, ...] = (
    "https://",
    "http://",
    "ssh://",
    "git://",
    "git@",
    "file://",
)

_COUNT_VAR = "GIT_CONFIG_COUNT"


def guarded_spawn_env(
    base_env: Mapping[str, str],
    *,
    active: bool,
    isolation: SpawnIsolation | None = None,
) -> dict[str, str] | None:
    """Собрать окружение спавна claude: ``None`` без мер, иначе база + git-конфиг мер.

    Чистая функция (mutation-цель) и ЕДИНСТВЕННЫЙ шов окружения спавна: две меры живут
    здесь вместе, потому что обе выражаются одним и тем же блоком ``GIT_CONFIG_*``, а
    второй механизм рядом с этим неизбежно разошёлся бы с ним по нумерации пар.

    * ``active`` (owner-ослабление ``coder.allow_bypass``) — барьер push'а bob-5ao: по
      паре ``GIT_CONFIG_KEY_i`` / ``GIT_CONFIG_VALUE_i`` на каждый префикс из
      :data:`PUSH_GUARD_URL_PREFIXES`. Снимается изнутри и кредов НЕ убирает — это
      страховка от нечаянного push, второй слой.
    * ``isolation`` (BOB-089, срез C; ``coder.isolated_clone``) — изоляция от кредов
      owner'а: подменный global-конфиг, отключённый системный, сброшенный список
      credential-хелперов, ``GIT_TERMINAL_PROMPT=0``, ``GIT_ASKPASS`` в никуда, и из
      окружения ВЫЧИЩАЮТСЯ :data:`~bob.identity.spawn_isolation.OWNER_CREDENTIAL_VARS`
      (``gh``-токен, сокет ssh-агента). Решения — в чистом ядре
      :mod:`bob.identity.spawn_isolation`; здесь только склейка с окружением.

    Обе выключены → ``None``, что вызывающий передаёт как «без ``env=``»: спавн
    байт-в-байт прежний. Иначе возвращается КОПИЯ ``base_env`` (claude нужны
    PATH/HOME/его собственные токены — меры дополняют окружение, а не заменяют его).

    🔴 ПОРЯДОК ПАР — ЧАСТЬ СМЫСЛА. Уже существующий в ``base_env`` блок ``GIT_CONFIG_*``
    уважается: нумерация продолжается с его ``GIT_CONFIG_COUNT``, а итоговый счётчик —
    сумма. Иначе наши пары встали бы на чужие индексы, настройки owner'а молча
    превратились бы в наши, а сброс хелперов оказался бы ПЕРЕД его helper'ом — то есть
    креды owner'а снова отвечали бы git'у. Нечисловой счётчик (git его тоже не прочитает)
    считается отсутствующим.
    """
    if not active and isolation is None:
        return None
    raw_count = base_env.get(_COUNT_VAR, "").strip()
    start = int(raw_count) if raw_count.isdigit() else 0
    env = dict(base_env)
    pairs: list[tuple[str, str]] = []
    if active:
        pairs += [
            (f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf", prefix)
            for prefix in PUSH_GUARD_URL_PREFIXES
        ]
    if isolation is not None:
        for var in OWNER_CREDENTIAL_VARS:
            env.pop(var, None)
        env.update(isolation_env(isolation))
        pairs += list(isolation_config_pairs(isolation))
    for offset, (key, value) in enumerate(pairs):
        index = start + offset
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    env[_COUNT_VAR] = str(start + len(pairs))
    return env
