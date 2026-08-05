# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Запрос разрешения на ЖИВОМ композиционном корне (BOB-090.E).

🔴 Отдельно от юнита проводки, и намеренно: зелёная проводка ничего не значит, если
композиция зовёт её не теми деталями (урок BOB-087.D5b). Здесь собирается весь граф
``build_application`` и проверяется, ЧЕМ он снабдил гейт привилегий:

* бот — БОБА, а не GUPPI: по канону (:func:`~bob.coding.speaker.speaker_for`) просьба о
  разрешении это социальный акт, и говорит её Боб;
* ростер — живой стор первых впечатлений: иначе упоминание owner'а заземлять нечем и
  Боб навсегда остался бы без настоящего ``@ника``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bob.app import build_application
from bob.coding.speaker import MessageKind, Speaker, speaker_for
from bob.runtime import composition
from bob.runtime.wiring.permission import _build_permission_flow
from bob.social.adapters.first_impression_store import SqliteFirstImpressionStore
from bob.social.adapters.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    import pytest


class _NullProvider:
    """Fake LLMProvider: никогда не вызывается — тест смотрит только на проводку."""

    async def complete(self, messages: Sequence[Mapping[str, str]], **kwargs: Any) -> str:
        del messages, kwargs
        raise NotImplementedError  # pragma: no cover


class _FakeBot:
    """Минимальный BotLike: сеть не трогается, ни один вызов здесь не делается."""

    def __init__(self, name: str) -> None:
        self.name = name

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[object]:
        del offset, timeout
        return []

    async def send_message(self, **kwargs: Any) -> Any:
        raise NotImplementedError  # pragma: no cover

    async def send_rich_message(self, **kwargs: Any) -> Any:
        raise NotImplementedError  # pragma: no cover

    async def send_chat_action(self, **kwargs: Any) -> Any:
        raise NotImplementedError  # pragma: no cover

    async def send_photo(self, **kwargs: Any) -> Any:
        raise NotImplementedError  # pragma: no cover

    async def send_document(self, **kwargs: Any) -> Any:
        raise NotImplementedError  # pragma: no cover

    async def set_message_reaction(self, **kwargs: Any) -> Any:
        raise NotImplementedError  # pragma: no cover


def _seed_soul(tmp_path: Path) -> None:
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nЯ Боб.\n")
    zero = {
        "valence": 0.0,
        "arousal": 0.0,
        "openness": 0.0,
        "social": 0.0,
        "stability": 0.0,
    }
    store.write_json("mood", {"baseline": zero, "current": zero})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 0},
        "llm": {
            "tier0_base_url": "http://localhost:8080/v1",
            "tier0_model": "tier0",
            "tier1_base_url": "https://api.example/v1",
            "tier1_model": "tier1",
            "tier1_api_key": "sk-test",
        },
        "telegram": {
            "poll_timeout": 1,
            "chat_id": -1004372947307,
            "owner_id": 7,
            "allowed_chat_ids": [-1004372947307],
            "bob": {"token": "bob-tok", "topic_id": 32},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _permission_wiring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], _FakeBot, _FakeBot]:
    """Собрать приложение и перехватить, ЧЕМ композиция снабдила гейт привилегий."""
    captured: dict[str, Any] = {}

    # Any здесь оправдан: шпион прозрачно пропускает КЛЮЧЕВЫЕ АРГУМЕНТЫ настоящего
    # билдера, не зная и не фиксируя их типы — их фиксирует сам билдер.
    def spy(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _build_permission_flow(**kwargs)

    monkeypatch.setattr(composition, "_build_permission_flow", spy)
    _seed_soul(tmp_path)
    bob_bot, guppi_bot = _FakeBot("bob"), _FakeBot("guppi")
    build_application(
        config=_config(tmp_path),
        providers={0: _NullProvider(), 1: _NullProvider()},
        bob_bot=bob_bot,  # type: ignore[arg-type]
        guppi_bot=guppi_bot,  # type: ignore[arg-type]
    )
    return captured, bob_bot, guppi_bot


def test_the_permission_notice_is_wired_to_bobs_bot_not_guppis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured, bob_bot, guppi_bot = _permission_wiring(tmp_path, monkeypatch)

    # Канон называет говорящего…
    assert speaker_for(MessageKind.PERMISSION_REQUEST) is Speaker.BOB
    # … а композиция даёт ровно его бота.
    assert captured["bot"] is bob_bot
    assert captured["bot"] is not guppi_bot


def test_the_permission_flow_gets_the_live_roster_for_the_owner_mention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured, _, _ = _permission_wiring(tmp_path, monkeypatch)

    # Без ростера настоящий @ник взять неоткуда — и owner навсегда остался бы по имени.
    assert isinstance(captured["directory"], SqliteFirstImpressionStore)
