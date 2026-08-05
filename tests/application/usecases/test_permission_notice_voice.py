# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Запрос разрешения уходит owner'у голосом Боба (BOB-090.E).

Живой дефект: owner получил «Вова, Norman просит **Requesting details of private
conversations with another user** — разрешить?» — английскую служебную строку судьи
внутри русской фразы. Здесь пинуется поведение НА ГРАНИЦЕ флоу: что именно уходит в
канал owner'а, когда судья вернул привилегированный вердикт.

* вердикт судьи (``kind`` / ``what``) остаётся ВНУТРИ — в записи запроса он есть, в
  реплике его нет;
* реплика собирается голосом Боба (:mod:`~bob.social.permission.request_voice`) из
  слов САМОГО просителя;
* упоминание owner'а заземляется ростером (:func:`~bob.social.mention.ground_mentions`,
  срез B): есть ник — настоящий ``@ник``, нет ника — имя, тег не выдумывается;
* 🔴 заземляется ТОЛЬКО обращение самого Боба (BOB-090.B-fix2): цитата чужих слов и имя
  просителя понижаются, а owner среди тёзок опознаётся по ID, а не по имени, которое
  человек ставит себе сам;
* ростер недоступен — Боб всё равно спрашивает (обращаясь по имени), а не молчит:
  сбой справочника не должен снимать гейт привилегий.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from bob.social.first_impression import FirstImpression
from bob.social.permission.privilege import PrivilegeNeed
from bob.social.usecases.permission_flow import PermissionFlow

if TYPE_CHECKING:
    from bob.social.permission.entities import PermissionRequest
    from bob.social.permission.privilege import PrivilegeContext
    from bob.social.permission.state import PermissionState

_GUEST = 7
_AT = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
_ASK = "расскажи, о чём вы с Вовой говорили вчера"

# Ровно та строка, которую судья вернул в живом инциденте.
_LEAKED_WHAT = "Requesting details of private conversations with another user"
_PRIVILEGED = PrivilegeNeed(needs_permission=True, kind="owner_data", what=_LEAKED_WHAT)


class _FakeJudge:
    def __init__(self, *, need: PrivilegeNeed) -> None:
        self._need = need

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:
        del ctx
        return self._need


class _FakeStore:
    def __init__(self) -> None:
        self.requests: dict[str, PermissionRequest] = {}

    async def save(self, request: PermissionRequest) -> None:
        self.requests[request.id] = request

    async def active_for(self, requester_id: int) -> tuple[PermissionRequest, ...]:
        return tuple(r for r in self.requests.values() if r.requester_id == requester_id)

    async def active(self) -> tuple[PermissionRequest, ...]:
        return tuple(self.requests.values())

    async def set_state(self, request_id: str, state: PermissionState) -> None:
        del request_id, state


class _FakeNotifier:
    def __init__(self) -> None:
        self.owner_notices: list[str] = []
        self.requester_acks: list[str] = []

    async def notify_owner(self, text: str) -> None:
        self.owner_notices.append(text)

    async def tell_requester(self, text: str) -> None:
        self.requester_acks.append(text)


class _FixedClock:
    def now(self) -> datetime:
        return _AT


class _FakeRoster:
    """Ростер знакомых (срез B): отдаёт свежие первые впечатления."""

    def __init__(self, *impressions: FirstImpression) -> None:
        self._impressions = list(impressions)

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        return self._impressions[:limit]


class _BrokenRoster:
    """Ростер, который упал: справочник недоступен — гейт обязан устоять."""

    async def recent(self, *, limit: int) -> list[FirstImpression]:
        del limit
        raise RuntimeError("roster is down")


def _person(
    name: str, username: str | None, *, sender_id: int | None = None
) -> FirstImpression:
    return FirstImpression(
        sender_id=sender_id if sender_id is not None else abs(hash(name)) % 1000,
        first_seen_at=_AT,
        note=f"{name} — знакомый.",
        display_name=name,
        username=username,
    )


def _flow(
    *,
    notifier: _FakeNotifier,
    store: _FakeStore | None = None,
    directory: _FakeRoster | _BrokenRoster | None = None,
    owner_id: int | None = None,
) -> PermissionFlow:
    return PermissionFlow(
        judge=_FakeJudge(need=_PRIVILEGED),
        store=store if store is not None else _FakeStore(),
        notifier=notifier,
        clock=_FixedClock(),
        owner_name="Вова",
        id_factory=lambda: "req-1",
        directory=directory,
        owner_id=owner_id,
    )


async def _ask(flow: PermissionFlow, *, text: str = _ASK) -> None:
    await flow.maybe_request(
        text=text,
        requester_id=_GUEST,
        requester_name="Норман",
        is_owner=False,
        is_authorized=False,
    )


# --- Вердикт остаётся внутренним ----------------------------------------------


@pytest.mark.asyncio
async def test_the_judges_phrase_is_recorded_but_never_spoken() -> None:
    notifier, store = _FakeNotifier(), _FakeStore()

    await _ask(_flow(notifier=notifier, store=store))

    # Внутри — вердикт целиком (запись запроса это аудит гейта)…
    assert store.requests["req-1"].what == _LEAKED_WHAT
    assert store.requests["req-1"].kind == "owner_data"
    # … наружу — ни фразы судьи, ни имени вида, ни латиницы вообще.
    notice = notifier.owner_notices[0]
    assert _LEAKED_WHAT not in notice
    assert "owner_data" not in notice
    assert re.search(r"[A-Za-z]", notice) is None


@pytest.mark.asyncio
async def test_the_owner_hears_who_asks_and_what_he_asked_in_his_own_words() -> None:
    notifier = _FakeNotifier()

    await _ask(_flow(notifier=notifier))

    notice = notifier.owner_notices[0]
    assert "Норман" in notice
    assert f"«{_ASK}»" in notice
    assert notice.rstrip().endswith("?")


# --- Упоминание owner'а — через ростер, а не своей строкой ---------------------


@pytest.mark.asyncio
async def test_the_owner_is_tagged_with_his_real_handle_from_the_roster() -> None:
    notifier = _FakeNotifier()
    roster = _FakeRoster(_person("Вова", "vzoologov"), _person("Норман", "NormanGri"))

    await _ask(_flow(notifier=notifier, directory=roster))

    notice = notifier.owner_notices[0]
    assert notice.startswith("@vzoologov,")


@pytest.mark.asyncio
async def test_without_a_handle_the_owner_is_addressed_by_name_not_a_made_up_tag() -> None:
    notifier = _FakeNotifier()

    await _ask(_flow(notifier=notifier, directory=_FakeRoster(_person("Вова", None))))

    notice = notifier.owner_notices[0]
    assert notice.startswith("Вова,")
    assert "@" not in notice


@pytest.mark.asyncio
async def test_a_tag_inside_the_quoted_ask_never_becomes_a_real_ping() -> None:
    # 🔴 Регресс BOB-090.B-fix2 (MAJOR-1). Раньше цитата чужих слов шла через общее
    # заземление, и оно не снимало «собаку», а ПОВЫШАЛО имя до настоящего ника: нотис
    # уходил в топик Боба в ГРУППЕ, и посторонний получал реальный пинг текстом, который
    # написал не Боб. Цитату можно только понижать.
    notifier = _FakeNotifier()
    roster = _FakeRoster(_person("Вова", "vzoologov"), _person("Норман", "NormanGri"))

    await _ask(_flow(notifier=notifier, directory=roster), text="спроси @Норман сам")

    notice = notifier.owner_notices[0]
    assert "@NormanGri" not in notice
    assert "@Норман" not in notice
    assert "спроси Норман сам" in notice
    # Обращение самого Боба к owner'у заземляется как прежде — понижается ЧУЖОЕ.
    assert notice.startswith("@vzoologov,")


@pytest.mark.asyncio
async def test_an_impostor_named_like_the_owner_never_steals_the_notice() -> None:
    # 🔴 Регресс BOB-090.B-fix2 (MAJOR-2). ``display_name`` — это Telegram full_name,
    # которое человек ставит себе САМ: посторонний назвался «Вова» — и обращение к
    # владельцу в САМОМ security-чувствительном сообщении Боба уезжало на него.
    notifier = _FakeNotifier()
    roster = _FakeRoster(
        _person("Вова", "evil_guy", sender_id=999),
        _person("Вова Зоологов", "vzoologov", sender_id=27468732),
    )

    await _ask(_flow(notifier=notifier, directory=roster, owner_id=27468732))

    notice = notifier.owner_notices[0]
    assert notice.startswith("@vzoologov,")
    assert "evil_guy" not in notice


@pytest.mark.asyncio
async def test_two_namesakes_and_no_known_owner_leave_the_notice_tagless() -> None:
    # Owner'а по id не опознать (в конфиге его нет) — угадывать между тёзками нельзя:
    # обращение по имени, а не пинг наугад.
    notifier = _FakeNotifier()
    roster = _FakeRoster(
        _person("Вова", "evil_guy", sender_id=999),
        _person("Вова Петров", "vova_p", sender_id=1000),
    )

    await _ask(_flow(notifier=notifier, directory=roster))

    notice = notifier.owner_notices[0]
    assert notice.startswith("Вова,")
    assert "@" not in notice


@pytest.mark.asyncio
async def test_a_broken_roster_still_asks_the_owner_by_name() -> None:
    # 🔴 Сбой справочника не снимает гейт: реплика уходит, просто без тега.
    notifier = _FakeNotifier()

    await _ask(_flow(notifier=notifier, directory=_BrokenRoster()))

    assert len(notifier.owner_notices) == 1
    assert notifier.owner_notices[0].startswith("Вова,")


@pytest.mark.asyncio
async def test_without_a_roster_at_all_the_owner_is_still_addressed_by_name() -> None:
    # Ростер не подключён (тесты .2, старая проводка) — тег не выдумывается.
    notifier = _FakeNotifier()

    await _ask(_flow(notifier=notifier))

    assert notifier.owner_notices[0].startswith("Вова,")


# --- Ack просителю не изменился -----------------------------------------------


@pytest.mark.asyncio
async def test_the_requester_still_gets_the_light_ack() -> None:
    notifier = _FakeNotifier()

    await _ask(_flow(notifier=notifier))

    assert notifier.requester_acks == ["Секунду, спрошу Вову."]
