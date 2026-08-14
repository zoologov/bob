# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Канон ДОЕЗЖАЕТ до провайдера на СОБРАННОЙ проводке (BOB-096.10, review MAJOR-5).

🔴 Дефект, ради которого написан этот файл. Шов канона стерегли два архитектурных гарда
(``test_that_single_build_site_hands_the_router_the_canon`` и
``test_every_tool_loop_in_the_tree_is_handed_the_canon``), и оба проверяли, что рядом со
сборкой В ТЕКСТЕ ИСХОДНИКА встречается подстрока ``voice_canon=``. Значение не смотрел
никто, а ``None`` — легальное значение типа ``VoiceCanon | None``. Ревьюер выключил весь
механизм эпика одним словом и прогнал полный набор:

* ``runtime/wiring/permission.py`` → ``voice_canon=None`` — 7586 passed: дверь
  привилегированного исполнения вернулась ровно в состояние MAJOR-1 («You are Bob…
  Answer them directly, in character», инструменты, канона нет);
* ``runtime/composition.py`` → ``voice_canon=None`` — 7586 passed: шов роутера, то есть
  запрет на десятке дверей, выключен, и ни один тест этого не видит.

🔴 Это ТОТ ЖЕ класс, которым прошёл сам MAJOR-1: гард смотрел на ИМЯ модуля, мы переписали
его на СВОЙСТВО — и проверили свойство снова текстом. Пятый случай за два эпика (#37, #45,
#52, #53 и этот). Поэтому здесь не текст, а ПОВЕДЕНИЕ: композиция собирается так, как её
собирает прод (:func:`~bob.app.build_application` на конфиге формы живого, фейк ровно
один — сеть), через собранную проводку прогоняется настоящий ход, а провайдер записывает
payload, который РЕАЛЬНО до него доехал. Утверждается дословное присутствие канона в этом
payload'е — то есть ``None`` в любой из двух точек провязки красит эти тесты.

Образец конструкции — ``test_the_live_wiring_actually_composes_the_verdicts_precondition``
(эпик BOB-096): проверять фактическую сборку, а не её написание.

Текстовые гарды остаются на месте как дешёвый ранний сигнал (они краснеют быстрее и
объясняют понятнее), но защита теперь не на них: они ловят ФОРМУ, здесь — ФАКТ.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from bob.app import build_application
from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.capabilities.ports import ToolCallResult
from bob.personality.voice import guppi_voice_canon
from bob.runtime import composition
from bob.runtime.wiring import permission as permission_wiring
from bob.social.adapters.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from types import ModuleType

    from bob.application.usecases.privileged_fulfiller import PrivilegedRequestFulfiller
    from bob.capabilities.ports import ToolDefinition
    from bob.kernel.ports import LLMMessage, ToolLoopMessage

_CHAT_ID = -1004372947307
_OWNER_ID = 7
_REQUESTER = "Норман"
_ASK = "покажи, что вы с Вовой решили вчера"


class _RecordingProvider:
    """Провайдер, который записывает payload, реально доехавший до модели.

    Одна деталь-фейк во всём файле — сеть. Обе ручки настоящие по контракту:
    ``complete`` (порт :class:`~bob.kernel.ports.LLMProvider`, путь роутера) и
    ``complete_with_tools`` (порт
    :class:`~bob.capabilities.ports.ToolCallingProvider`, путь тул-лупа). Вторая нужна
    не для полноты: композиция выбирает тул-провайдер по наличию ИМЕННО этого метода
    (:func:`~bob.runtime.wiring.access._as_tool_provider`), и без него привилегированное
    исполнение свернуло бы на путь роутера — а проверять надо тот, что идёт мимо него.
    """

    def __init__(self) -> None:
        self.plain: list[list[LLMMessage]] = []
        self.with_tools: list[list[ToolLoopMessage]] = []

    async def complete(self, messages: Sequence[LLMMessage], *, stream: bool = False) -> str:
        del stream
        self.plain.append(list(messages))
        return "ладно, посмотрел"

    async def complete_with_tools(
        self, messages: Sequence[ToolLoopMessage], *, tools: Sequence[ToolDefinition]
    ) -> ToolCallResult:
        del tools
        self.with_tools.append(list(messages))
        # Инструмент не запрашивается: ход финальный, и петля возвращает этот текст.
        return ToolCallResult(text="ладно, посмотрел")


class _FakeBot:
    """Минимальный BotLike: сеть не трогается, ни один вызов здесь не делается."""

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
    """Положить душу на диск, чтобы сборка шла как на живом старте (без Genesis)."""
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nЯ Боб.\n")
    zero = {"valence": 0.0, "arousal": 0.0, "openness": 0.0, "social": 0.0, "stability": 0.0}
    store.write_json("mood", {"baseline": zero, "current": zero})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


def _config(tmp_path: Path) -> dict[str, object]:
    """Конфиг ФОРМЫ живого: два тира, два бота, настоящие пути персистенса."""
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
            "chat_id": _CHAT_ID,
            "owner_id": _OWNER_ID,
            "allowed_chat_ids": [_CHAT_ID],
            "bob": {"token": "bob-tok", "topic_id": 32},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


# ``Any`` здесь обоснован: шпион ПРОЗРАЧЕН — он пропускает конструктор насквозь, не зная и
# не фиксируя ни его аргументы, ни тип результата (их фиксирует сам конструктор). Тест
# смотрит на ПОВЕДЕНИЕ пойманного объекта, а не на его типизацию.
def _capture_built(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str
) -> list[Any]:
    """Перехватить объекты, которые НАСТОЯЩАЯ сборка создала под этим именем."""
    real = getattr(module, name)
    built: list[Any] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        instance = real(*args, **kwargs)
        built.append(instance)
        return instance

    monkeypatch.setattr(module, name, spy)
    return built


def _compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[_RecordingProvider, LLMRouter, PrivilegedRequestFulfiller]:
    """Собрать граф как прод и отдать провайдер + две двери, стоящие на точках прохода."""
    routers = _capture_built(monkeypatch, composition, "LLMRouter")
    fulfillers = _capture_built(monkeypatch, permission_wiring, "PrivilegedRequestFulfiller")
    _seed_soul(tmp_path)
    provider = _RecordingProvider()

    build_application(
        config=_config(tmp_path),
        # Провайдер подходит по ПОРТУ (структурно) — приведения не нужно: композиция
        # получает ровно то, что получила бы от настоящей фабрики тиров.
        providers={0: provider, 1: provider},
        bob_bot=_FakeBot(),  # type: ignore[arg-type]
        guppi_bot=_FakeBot(),  # type: ignore[arg-type]
    )

    # Анти-вакуум: ловим ровно те объекты, которые собрал прод, и ровно по одному.
    assert len(routers) == 1, "композиция собрала не один роутер — тест ловит не то"
    assert len(fulfillers) == 1, "композиция собрала не один фулфиллер — тест ловит не то"
    return provider, routers[0], fulfillers[0]


async def test_the_composed_router_sends_the_canon_to_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ход двери-голоса через СОБРАННЫЙ роутер увозит запрет модели дословно.

    Дверь взята намеренно НЕ разговорная (рефлексия): базовая персона несёт запрет
    сама, поэтому разговорный ход остался бы зелёным и с выключенным швом — то есть
    ничего не доказывал бы. Рефлексия получает канон ТОЛЬКО от роутера.
    """
    provider, router, _ = _compose(tmp_path, monkeypatch)

    answer = await router.run(
        LLMRequest(
            task_type=TaskType.REFLECT,
            messages=[{"role": "user", "content": "о чём я сегодня думал"}],
        )
    )

    assert answer == "ладно, посмотрел"
    assert len(provider.plain) == 1, "до провайдера вообще не доехало — проверять нечего"
    sent = [str(message["content"]) for message in provider.plain[0]]
    assert guppi_voice_canon(prose_answer=True) in sent


async def test_the_composed_privileged_fulfilment_sends_the_canon_to_the_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Привилегированное исполнение увозит запрет модели дословно — на ПУТИ С ИНСТРУМЕНТАМИ.

    Ровно та дверь, что была MAJOR-1: она сочиняет свой промпт «You are Bob… Answer them
    directly, in character», уходит к провайдеру тул-лупом мимо роутера и умеет ходить
    инструментами. Канон приходит ей только из ``runtime/wiring/permission.py``.
    """
    provider, _, fulfiller = _compose(tmp_path, monkeypatch)

    answer = await fulfiller.fulfil(_ASK, requester_id=555, requester_name=_REQUESTER)

    assert answer == "ладно, посмотрел"
    # 🔴 Анти-вакуум: путь должен быть ИМЕННО тул-луповый. Свернув на роутер, фулфиллер
    # получил бы канон от него — и тест был бы зелёным при выключенной провязке.
    assert provider.plain == [], "исполнение свернуло на роутер — проверяется не та дверь"
    assert len(provider.with_tools) == 1, "тул-луп до провайдера не доехал"
    sent = [str(message["content"]) for message in provider.with_tools[0]]
    assert guppi_voice_canon(prose_answer=True) in sent


async def test_the_privileged_prompt_that_earned_this_test_is_still_the_one_being_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """🔴 Второй анти-вакуум: канон едет РЯДОМ с тем самым промптом, а не вместо него.

    Без этого «канон доехал» осталось бы правдой и в мире, где промпт привилегированного
    исполнения переписали или потеряли, — а именно его формулировка («ты Боб, отвечай
    в характере», плюс инструменты) и делает эту дверь опасной.
    """
    provider, _, fulfiller = _compose(tmp_path, monkeypatch)

    await fulfiller.fulfil(_ASK, requester_id=555, requester_name=_REQUESTER)

    sent = "\n".join(str(message["content"]) for message in provider.with_tools[0])
    assert "You are Bob" in sent
    assert _REQUESTER in sent
    assert _ASK in sent


@pytest.mark.parametrize("prose_answer", [True, False])
def test_the_canon_text_is_never_empty(prose_answer: bool) -> None:
    """Анти-вакуум над самим утверждением: пустая строка нашлась бы в любом payload'е."""
    assert guppi_voice_canon(prose_answer=prose_answer).strip() != ""
