# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Инструмент отправки на ЖИВОМ композиционном корне (BOB-090.B1).

🔴 Отдельно от юнит-теста проводки, и намеренно: зелёная проводка ничего не значит, если
композиционный корень её не зовёт (урок BOB-087.D5b — юнит зелёный, в проде мертво).
Здесь собирается ВЕСЬ граф ``build_application`` и проверяется манифест реестра, который
реально увидит модель.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bob.app import build_application
from bob.social.adapters.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


class _NullProvider:
    """Fake LLMProvider: никогда не вызывается — тест смотрит только манифест."""

    async def complete(
        self, messages: Sequence[Mapping[str, str]], **kwargs: Any
    ) -> str:
        del messages, kwargs
        raise NotImplementedError  # pragma: no cover


class _FakeBot:
    """Минимальный BotLike: сеть не трогается, ни один вызов в этих тестах не делается."""

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[object]:
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


def _config(tmp_path: Path, *, social: Mapping[str, object] | None = None) -> dict[str, object]:
    config: dict[str, object] = {
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
    if social is not None:
        config["social"] = social
    return config


def _tool_names(tmp_path: Path, *, social: Mapping[str, object] | None) -> set[str]:
    _seed_soul(tmp_path)
    bot = _FakeBot()
    app = build_application(
        config=_config(tmp_path, social=social),
        providers={0: _NullProvider(), 1: _NullProvider()},
        bob_bot=bot,  # type: ignore[arg-type]
        guppi_bot=bot,  # type: ignore[arg-type]
    )
    return {
        str(tool["function"]["name"])  # type: ignore[index]
        for tool in app.registry.manifest()
    }


def test_the_delivery_tool_is_absent_by_default(tmp_path: Path) -> None:
    # Флаг выключен → модель не видит инструмента вовсе, ход байт-в-байт прежний.
    assert "send_to_chat" not in _tool_names(tmp_path, social=None)


def test_the_flag_puts_the_delivery_tool_on_the_live_manifest(tmp_path: Path) -> None:
    assert "send_to_chat" in _tool_names(tmp_path, social={"delivery": True})
