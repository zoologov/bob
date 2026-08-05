# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Живой композиционный корень как ГРАНИЦА для сценариев BOB-090.

🔴 Здесь собирается весь граф :func:`~bob.app.build_application` — настоящая SQLite с
настоящим FTS5, настоящий ростер, настоящий реестр capability, настоящий tool-loop, — а
фейки стоят ровно там, где кончается Боб:

* :class:`RecordingBot` — телеграм-бот ОДНОЙ личности (Боба или GUPPI): записывает чат,
  топик и текст каждой отправки, то есть ровно то, что увидел бы человек в комнате;
* :class:`Tier0Provider` / :class:`Tier1Provider` — обе ступени модели: Tier-0 отвечает
  классификаторам их же размеченным форматом (парсеры вердиктов остаются НАСТОЯЩИМИ), а
  Tier-1 сочиняет реплику и, если сценарий просит, зовёт инструмент проводом — тело ответа
  разбирает настоящий парсер OpenAI-совместимого эндпоинта.

Урок BOB-087.D5b: зелёная проводка на фейке ничего не говорит о том, что делает прод, —
поэтому сценарии эпика ездят через эту сборку, а не через ручной граф из деталей.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from bob.app import build_application
from bob.infrastructure.llm.openai_compat import _extract_tool_call_result
from bob.social.adapters.first_impression_store import SqliteFirstImpressionStore
from bob.social.adapters.soul_store import SoulStore
from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE
from bob.social.first_impression import FirstImpression

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from bob.capabilities.ports import ToolCallResult, ToolDefinition
    from bob.kernel.ports import ToolLoopMessage
    from bob.runtime.composition import Application

# Живые адреса сценариев: комната с форум-топиком Боба и личка owner'а (её chat_id в
# Telegram равен user id owner'а — ровно как в проде).
OWNER_ID = 27468732
GROUP_CHAT_ID = -1004372947307
BOB_TOPIC_ID = 32
OWNER_DM_CHAT_ID = OWNER_ID
NORMAN_ID = 6001
NORMAN_NAME = "Норман"
NORMAN_USERNAME = "NormanGri"

# Общее зерно вероятностных жестов Боба (штатный параметр композиционного корня).
_SCENARIO_SEED = 7


@dataclass(frozen=True, slots=True)
class SentLine:
    """Одна отправленная строка, как её видит получатель: где, в каком треде и что."""

    chat_id: int
    topic_id: int | None
    text: str


@dataclass
class RecordingBot:
    """Фейковый бот ОДНОЙ личности: записывает всё, что его попросили отправить."""

    name: str
    sent: list[SentLine] = field(default_factory=list)

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[object]:
        del offset, timeout
        return []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> _FakeMessage:
        del reply_parameters
        self.sent.append(SentLine(chat_id, message_thread_id, text))
        return _FakeMessage()

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: Any,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> _FakeMessage:
        del reply_parameters
        markdown = getattr(rich_message, "markdown", "") or ""
        self.sent.append(SentLine(chat_id, message_thread_id, markdown))
        return _FakeMessage()

    async def send_chat_action(self, **kwargs: Any) -> bool:
        del kwargs
        return True

    async def set_message_reaction(self, **kwargs: Any) -> bool:
        del kwargs
        return True

    async def send_photo(self, **kwargs: Any) -> _FakeMessage:  # pragma: no cover
        del kwargs
        raise NotImplementedError

    async def send_document(self, **kwargs: Any) -> _FakeMessage:  # pragma: no cover
        del kwargs
        raise NotImplementedError

    def to(self, chat_id: int) -> tuple[SentLine, ...]:
        """Всё, что этот бот отправил в указанный чат."""
        return tuple(line for line in self.sent if line.chat_id == chat_id)

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(line.text for line in self.sent)


@dataclass
class _FakeMessage:
    message_id: int = 1
    text: str | None = None
    message_thread_id: int | None = None


class Tier0Provider:
    """Tier-0: отвечает классификаторам по маркерам их промптов (сеть не трогается).

    Единственный «фейк модели»: настоящие ПАРСЕРЫ вердиктов остаются в деле — провайдер
    отдаёт им ту же размеченную строку, что вернула бы живая Qwen. ``privilege`` включает
    вердикт судьи привилегий (срез E), ``consent`` — согласие owner'а на вынос приватного.
    """

    def __init__(
        self,
        *,
        consent: bool = True,
        privilege: Mapping[str, str] | None = None,
    ) -> None:
        self._consent = consent
        self._privilege = privilege
        self.consent_calls = 0
        self.privilege_calls = 0

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False
    ) -> str:
        del stream
        prompt = "\n".join(str(message.get("content", "")) for message in messages)
        if "consent: <yes|no>" in prompt:
            self.consent_calls += 1
            return f"consent: {'yes' if self._consent else 'no'}"
        if "needs_permission:" in prompt:
            self.privilege_calls += 1
            return _privilege_reply(self._privilege)
        if "how to respond socially" in prompt:
            return "intent: reply\nreason: harness"
        return "no"


def _privilege_reply(privilege: Mapping[str, str] | None) -> str:
    """Ответ судьи привилегий в его же размеченном формате (парсер настоящий)."""
    if privilege is None:
        return "needs_permission: нет\nkind: \nwhat: "
    return (
        f"needs_permission: да\nkind: {privilege['kind']}\nwhat: {privilege['what']}"
    )


class Tier1Provider:
    """Tier-1: сочиняет реплику и, если попросили, ЗОВЁТ инструменты — проводом.

    ``prompts`` — системные промпты, которые Боб реально отдал модели (граница «что Боб
    сказал модели о себе»); ``tool_results`` — что инструменты вернули модели, её
    единственный источник правды об отправке.

    ``tool_calls`` (BOB-090.B-fix2) — ПОСЛЕДОВАТЕЛЬНОСТЬ вызовов, по одному на ход
    tool-loop: живая модель может сначала поднять память (``search_memory``), а потом
    отправить (``send_to_chat``), и именно этот путь обходил гейт переноса. ``tool_call``
    — прежняя короткая форма для одного ``send_to_chat``.
    """

    def __init__(
        self,
        *,
        reply: str,
        tool_call: Mapping[str, object] | None = None,
        tool_calls: Sequence[Mapping[str, object]] = (),
    ) -> None:
        self._reply = reply
        self._calls: list[tuple[str, Mapping[str, object]]] = [
            ("send_to_chat", call) for call in (tool_call,) if call is not None
        ]
        self._calls.extend(
            (str(call["name"]), _arguments_of(call)) for call in tool_calls
        )
        self.prompts: list[str] = []
        self.tool_results: list[str] = []
        self._next = 0

    async def complete(
        self, messages: Sequence[Mapping[str, str]], *, stream: bool = False
    ) -> str:
        del stream
        self._remember_prompt(messages)
        return self._reply

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        del tools
        self._remember_prompt(messages)
        self._remember_tool_results(messages)
        if self._next >= len(self._calls):
            return _extract_tool_call_result(_text_body(self._reply))
        name, arguments = self._calls[self._next]
        self._next += 1
        return _extract_tool_call_result(_call_body(name, arguments))

    def _remember_prompt(self, messages: Sequence[Mapping[str, object]]) -> None:
        for message in messages:
            if message.get("role") == "system":
                self.prompts.append(str(message.get("content", "")))

    def _remember_tool_results(self, messages: Sequence[ToolLoopMessage]) -> None:
        for message in messages:
            if message.get("role") == "tool":
                content = str(message.get("content", ""))
                if content not in self.tool_results:
                    self.tool_results.append(content)


def _arguments_of(call: Mapping[str, object]) -> Mapping[str, object]:
    """Аргументы одного запрошенного вызова (сценарий задаёт их картой)."""
    arguments = call.get("arguments", {})
    return arguments if isinstance(arguments, dict) else {}


def _call_body(name: str, arguments: Mapping[str, object]) -> dict[str, object]:
    """Тело ответа, в котором модель нативно просит инструмент ``name``."""
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call_{name}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(arguments, ensure_ascii=False),
                            },
                        }
                    ],
                }
            }
        ]
    }


def _text_body(text: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": text}}]}


def seed_soul(tmp_path: Path) -> None:
    """Заранее записать SOUL, чтобы Genesis на ходе был no-op."""
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


def live_config(
    tmp_path: Path,
    *,
    delivery: bool = False,
    origin_provenance: bool = False,
) -> dict[str, object]:
    """Конфиг ЖИВОГО контура: два бота, комната с топиком Боба, личка owner'а.

    ``coder.dev_dm`` включён так же, как в живом ``config/bob.yaml``: за этим флагом стоит
    контур согласия owner'а (BOB-082.4), и без него инструмент отправки не у кого спросить
    «выносить ли приватное» — а значит не вынесет ничего.
    """
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
            "chat_id": GROUP_CHAT_ID,
            "owner_id": OWNER_ID,
            "owner_dm_chat_id": OWNER_DM_CHAT_ID,
            "allowed_chat_ids": [GROUP_CHAT_ID],
            "bob": {"token": "bob-tok", "topic_id": BOB_TOPIC_ID},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
        "coder": {"dev_dm": True},
    }
    if delivery:
        config["social"] = {"delivery": True}
    if origin_provenance:
        config["memory"] = {"origin_provenance": True}
    return config


def build_live_app(
    tmp_path: Path,
    *,
    tier0: Tier0Provider,
    tier1: Tier1Provider,
    bob_bot: RecordingBot,
    guppi_bot: RecordingBot,
    delivery: bool = False,
    origin_provenance: bool = False,
) -> Application:
    """Собрать весь граф на двух записывающих ботах и двух фейковых ступенях модели.

    ``proactivity_seed`` — штатный шов детерминизма самого корня: у Боба есть намеренно
    вероятностные жесты (например, редкая вспоминка «что-то напомнило»), и без общего
    зерна два прогона одного и того же хода честно разойдутся. Сценариям нужно сравнивать
    ПОВЕДЕНИЕ, а не подбрасывание монетки, поэтому зерно фиксировано.
    """
    seed_soul(tmp_path)
    return build_application(
        config=live_config(
            tmp_path, delivery=delivery, origin_provenance=origin_provenance
        ),
        providers={0: tier0, 1: tier1},
        bob_bot=bob_bot,  # type: ignore[arg-type]
        guppi_bot=guppi_bot,  # type: ignore[arg-type]
        proactivity_seed=_SCENARIO_SEED,
    )


def offers_tool(app: Application, name: str) -> bool:
    """Видит ли модель инструмент ``name`` в живом манифесте реестра."""
    return any(
        str(tool["function"]["name"]) == name  # type: ignore[index]
        for tool in app.registry.manifest()
    )


async def remember_owner(app: Application, *, username: str | None) -> None:
    """Записать owner'а в ЖИВОЙ ростер (без записи его ник взять неоткуда)."""
    store = SqliteFirstImpressionStore(app.connection)
    await store.save(
        FirstImpression(
            sender_id=OWNER_ID,
            first_seen_at=datetime.now(UTC),
            note="Вова — твой владелец; этого человека ты знаешь.",
            display_name="Вова",
            username=username,
        )
    )


async def remember_private_moment(app: Application, *, content: str) -> None:
    """Записать в ЖИВУЮ память приватный эпизод из лички (так его пишет обычный ход).

    Материал, который Боб потом ДОБАВИТ от себя: recall поднимет эту запись по слову из
    просьбы, и гейт переноса увидит приватную метку — то есть сценарий проверяет тот же
    путь, что и прод, а не подставленное состояние инструмента.
    """
    await app.memory_repo.save_episode(
        {
            "ts": datetime.now(UTC).isoformat(),
            "event_type": "message",
            "content": content,
            "sender_id": OWNER_ID,
            "visibility": VISIBILITY_OWNER_PRIVATE,
        }
    )


async def remember_norman(app: Application, *, username: str | None) -> None:
    """Записать Нормана в ЖИВОЙ ростер — как это делает интейк настоящего хода."""
    store = SqliteFirstImpressionStore(app.connection)
    await store.save(
        FirstImpression(
            sender_id=NORMAN_ID,
            first_seen_at=datetime.now(UTC),
            note=f"{NORMAN_NAME} — кто-то из знакомых, уже виделись.",
            display_name=NORMAN_NAME,
            username=username,
        )
    )
