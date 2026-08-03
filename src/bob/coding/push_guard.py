# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=domain

"""Окружение спавна claude с запретом исходящего push — чистое ядро (BOB-087.E, bob-5ao).

ОДНА ответственность: собрать окружение процесса ``claude`` так, чтобы КАЖДЫЙ push по
сетевому URL из ослабленной песочницы упирался в несуществующий remote-helper. Делается
это git-конфигом через ``GIT_CONFIG_COUNT`` / ``GIT_CONFIG_KEY_i`` / ``GIT_CONFIG_VALUE_i``
(env-конфиг сильнее файлового и наследуется всеми дочерними процессами), а сам конфиг —
это набор ``url.<заглушка>.pushInsteadOf = <префикс>``: git переписывает push-URL,
начинающийся с префикса, в заглушку, и вызов умирает на ``remote helper '<схема>'``.
Fetch/clone не затрагиваются: правится ТОЛЬКО push (``pushInsteadOf``, не ``insteadOf``).

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
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

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
    base_env: Mapping[str, str], *, active: bool
) -> dict[str, str] | None:
    """Собрать окружение спавна claude: ``None`` без барьера, иначе база + git-конфиг.

    Чистая функция (mutation-цель). ``active=False`` (дефолт продукта — ``coder.allow_bypass``
    выключен) даёт ``None``, что вызывающий передаёт как «без ``env=``»: спавн байт-в-байт
    прежний. ``active=True`` возвращает КОПИЮ ``base_env`` (claude нужны PATH/HOME/токены —
    барьер дополняет окружение, а не заменяет его) плюс по паре ``GIT_CONFIG_KEY_i`` /
    ``GIT_CONFIG_VALUE_i`` на каждый префикс из :data:`PUSH_GUARD_URL_PREFIXES`.

    Уже существующий в ``base_env`` блок ``GIT_CONFIG_*`` уважается: нумерация продолжается
    с его ``GIT_CONFIG_COUNT``, а итоговый счётчик — сумма. Иначе наши пары встали бы на
    чужие индексы и настройки owner'а молча превратились бы в наши. Нечисловой счётчик
    (git его тоже не прочитает) считается отсутствующим.
    """
    if not active:
        return None
    raw_count = base_env.get(_COUNT_VAR, "").strip()
    start = int(raw_count) if raw_count.isdigit() else 0
    env = dict(base_env)
    for offset, prefix in enumerate(PUSH_GUARD_URL_PREFIXES):
        index = start + offset
        env[f"GIT_CONFIG_KEY_{index}"] = f"url.{PUSH_GUARD_STUB_URL}.pushInsteadOf"
        env[f"GIT_CONFIG_VALUE_{index}"] = prefix
    env[_COUNT_VAR] = str(start + len(PUSH_GUARD_URL_PREFIXES))
    return env
