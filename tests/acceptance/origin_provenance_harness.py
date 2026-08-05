# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Boundary-харнесс сценариев «Боб помнит, ГДЕ это было» (BOB-090.C, US-1).

Живой дефект эпика (эпизод 3092): в группе Боб заявил «я объяснил Норману в группе», а
объяснял в личке. Он не соврал — место до него просто не доходило.

Здесь ход прогоняется через живой композиционный корень
(:mod:`tests.acceptance.live_app_harness`): архив осаждается в настоящую SQLite, пул
собирает настоящий FTS5-recall, а наблюдаемым является ГРАНИЦА С МОДЕЛЬЮ — системный
промпт, который Боб реально отдал Tier-1. Именно там видно, назвал ли он место и какое:
приватного состояния композера и стора сценарии не касаются.

🔴 Флаг ``memory.origin_provenance`` OFF доказывается РАВЕНСТВОМ промптов, а не похожестью:
:func:`run_origin_turn` возвращает промпт хода целиком, и сценарий сравнивает строки.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.runtime.events import MessageReceived
from tests.acceptance.live_app_harness import (
    OWNER_DM_CHAT_ID,
    OWNER_ID,
    RecordingBot,
    Tier0Provider,
    Tier1Provider,
    build_live_app,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

__all__ = [
    "Memory",
    "OriginOutcome",
    "origin_lines",
    "run_origin_pair",
    "run_origin_turn",
]

# Куски провенанс-директив, по которым сценарий узнаёт, ЧТО Боб сказал себе о месте.
# Намеренно не полный текст: сценарий проверяет утверждение о месте, а не формулировку.
SAID_PRIVATELY = "сказано наедине"
SAID_IN_ROOM = "сказано в общем чате"
MIXED_ORIGINS = "пришло из разных мест"


@dataclass(frozen=True, slots=True)
class Memory:
    """Один эпизод архива: что было сказано и с какой пометкой источника.

    ``visibility`` ``None`` — легаси-строка, записанная до того, как источник вообще
    появился: «не знаю где», а НЕ «сказано при всех».
    """

    content: str
    visibility: str | None


@dataclass(slots=True)
class OriginOutcome:
    """Наблюдаемое: что Боб сказал модели о себе и что вообще припомнил."""

    prompt: str = ""
    recalled_contents: tuple[str, ...] = ()

    def claims(self, phrase: str) -> bool:
        """Утверждает ли Боб в этом ходе ``phrase`` про место припомненного."""
        return phrase in self.prompt

    @property
    def names_a_place(self) -> bool:
        """Назвал ли Боб место припомненного хоть как-нибудь."""
        return any(
            self.claims(phrase)
            for phrase in (SAID_PRIVATELY, SAID_IN_ROOM, MIXED_ORIGINS)
        )

    def recalled(self, needle: str) -> bool:
        """Всплыл ли в промпте хода эпизод с таким содержанием."""
        return needle in self.prompt


async def run_origin_turn(
    tmp_path: Path,
    *,
    archive: Sequence[Memory],
    question: str,
    origin_provenance: bool,
) -> OriginOutcome:
    """Осадить ``archive`` в настоящую память и задать ``question`` из лички owner'а.

    Возвращает системный промпт хода целиком (граница с моделью) и содержимое архива,
    чтобы сценарий мог утверждать и про названное место, и про сквозной recall.
    """
    bob_bot, guppi_bot = RecordingBot("bob"), RecordingBot("guppi")
    tier1 = Tier1Provider(reply="Ага.")
    app = build_live_app(
        tmp_path,
        tier0=Tier0Provider(),
        tier1=tier1,
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
        origin_provenance=origin_provenance,
    )
    await app.startup()
    try:
        await _seed(app, archive)
        await app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=OWNER_DM_CHAT_ID,
                message_id=31,
                text=question,
                sender_id=OWNER_ID,
                sender_name="Вова",
                is_group=False,
                topic_id=None,
            )
        )
    finally:
        await app.shutdown()
    return OriginOutcome(
        prompt=tier1.prompts[0] if tier1.prompts else "",
        recalled_contents=tuple(memory.content for memory in archive),
    )


async def run_origin_pair(
    tmp_path: Path, *, archive: Sequence[Memory], question: str
) -> tuple[OriginOutcome, OriginOutcome]:
    """Один и тот же ход при ВЫКЛЮЧЕННОМ и при включённом провенансе.

    Возвращает ``(off, on)``, чтобы сценарий доказывал OFF-путь РАВЕНСТВОМ строк, а не
    похожестью. Зерно вероятностных жестов Боба фиксировано композиционным корнем, так
    что расхождение может дать только сам провенанс.
    """
    off = await run_origin_turn(
        tmp_path / "off", archive=archive, question=question, origin_provenance=False
    )
    on = await run_origin_turn(
        tmp_path / "on", archive=archive, question=question, origin_provenance=True
    )
    return off, on


def origin_lines(prompt: str) -> tuple[str, ...]:
    """Строки промпта, в которых Боб утверждает что-то о МЕСТЕ припомненного."""
    return tuple(
        line
        for line in prompt.splitlines()
        if any(
            phrase in line for phrase in (SAID_PRIVATELY, SAID_IN_ROOM, MIXED_ORIGINS)
        )
    )


async def _seed(app: object, archive: Sequence[Memory]) -> None:
    """Записать архив настоящими эпизодами с их пометкой источника (или без неё)."""
    repo = app.memory_repo  # type: ignore[attr-defined]
    base = datetime(2026, 8, 4, 10, 0, tzinfo=UTC)
    for index, memory in enumerate(archive):
        episode: dict[str, object] = {
            "ts": base.replace(minute=index).isoformat(),
            "event_type": "message",
            "content": memory.content,
            "sender_id": OWNER_ID,
        }
        if memory.visibility is not None:
            episode["visibility"] = memory.visibility
        await repo.save_episode(episode)
