# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Живой смоук: из сессии Боба РЕАЛЬНО стартует субагент и видит файлы места (BOB-088, срез 4).

🔴 §0.3 п.4: тест на фейке доказывает контракт ФЕЙКА. Вся идея BOB-088 — «Боб ведёт эпик по
конвейеру», а конвейер держится на том, что роли (dev / test / review / tech-writer)
запускаются СУБАГЕНТАМИ из сессии и видят ``.claude/`` рабочего места. Это единственное
место, где утверждение проверяется НАСТОЯЩИМ ``claude``, а не мерой argv.

🔴 Урок собственной пробы (записан, чтобы не повторить): первый заход проверял ``tool_use``
по имени ``Task`` и выдал ложное «субагент не стартовал» — этот ``claude`` зовёт субагента
инструментом ``Agent``. «Не нашли по имени» — не «не случилось»: принимаем ОБА имени, а
доказательством служит ЭФФЕКТ — субагент вернул строку файла, которую без чтения ``.claude/``
взять неоткуда.

Выключен по умолчанию (нужны сеть и учётка ``claude``); включается ``BOB_LIVE_CLAUDE_SMOKE=1``.
Пропуск ВИДИМЫЙ и с причиной — молчаливого зелёного здесь не бывает.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from bob.interactive.adapters.runner import InteractiveClaudeRunner
from bob.interactive.pipeline_prompt import pipeline_first_frame

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

_LIVE_FLAG = "BOB_LIVE_CLAUDE_SMOKE"
_TIMEOUT_S = 180.0

#: Опознавательная первая строка роли в рабочем месте — субагент вернёт ЕЁ, и взять её
#: без чтения ``.claude/`` он не может.
_ROLE_MARK = "# РОЛЬ-МАЯК-BOB-088"

#: Имена, которыми РАЗНЫЕ версии CLI зовут запуск субагента (см. урок в докстроке).
_SUBAGENT_TOOLS = frozenset({"Agent", "Task"})

pytestmark = [
    pytest.mark.skipif(
        os.environ.get(_LIVE_FLAG) != "1",
        reason=f"живой смоук выключен: не задан {_LIVE_FLAG}=1 (настоящий claude, сеть)",
    ),
    pytest.mark.skipif(
        shutil.which("claude") is None, reason="claude не установлен в этой системе"
    ),
    pytest.mark.skipif(
        shutil.which("git") is None, reason="настоящий git недоступен в этой системе"
    ),
]


@pytest.fixture
def workplace(tmp_path: Path) -> Path:
    """Минимальное рабочее место с одним файлом роли — то, что субагент прочтёт."""
    work = tmp_path / "work"
    agents = work / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "dev.md").write_text(
        f"{_ROLE_MARK}\nРоль dev: реализует беаду по TDD.\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=work, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=work, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=o@e.com", "-c", "user.name=O", "commit", "-m", "init"],
        cwd=work,
        check=True,
        capture_output=True,
    )
    return work


async def _run(workdir: Path, task: str) -> list[Mapping[str, object]]:
    """Поднять ПРОДАКШН-раннер и дать ему постановку ПЕРВЫМ КАДРОМ конвейера."""
    frame = pipeline_first_frame(task)
    assert frame is not None
    runner = InteractiveClaudeRunner()
    await runner.open(str(workdir), mode="acceptEdits")
    events: list[Mapping[str, object]] = []
    try:
        await runner.feed(frame)

        async def _read() -> None:
            async for event in runner.events():
                events.append(event)
                if event.get("type") == "result":
                    return

        await asyncio.wait_for(_read(), timeout=_TIMEOUT_S)
    finally:
        await runner.close()
    return events


def _subagent_launches(events: list[Mapping[str, object]]) -> list[str]:
    """Имена запусков субагента в потоке — по ОБОИМ известным именам инструмента."""
    launched: list[str] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        content = message.get("content", []) if isinstance(message, dict) else []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name")
                if name in _SUBAGENT_TOOLS:
                    launched.append(str(name))
    return launched


def _returned_texts(events: list[Mapping[str, object]]) -> str:
    """Весь ассистентский текст сессии — там всплывёт строка, прочитанная субагентом."""
    chunks: list[str] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        message = event.get("message")
        content = message.get("content", []) if isinstance(message, dict) else []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
    return "\n".join(chunks)


@pytest.mark.asyncio
async def test_a_subagent_starts_and_reads_a_role_file_from_the_workplace(
    workplace: Path,
) -> None:
    events = await _run(
        workplace,
        "Проверка связи конвейера. Запусти РОВНО ОДНОГО субагента через инструмент "
        "запуска субагента; пусть он прочитает файл .claude/agents/dev.md и вернёт его "
        "ПЕРВУЮ строку дословно. Верни мне эту строку. Больше ничего не делай, беады "
        "не трогай.",
    )

    launches = _subagent_launches(events)
    assert launches, (
        "субагент не стартовал ни под именем Agent, ни под Task: "
        f"{json.dumps(events, ensure_ascii=False)[:2000]}"
    )
    # 🔴 ЭФФЕКТ, а не только вызов: строку-маяк субагент мог вернуть, лишь прочитав файл
    # из ``.claude/`` рабочего места — значит место он видит.
    assert _ROLE_MARK in _returned_texts(events), (
        f"строка-маяк роли не вернулась — субагент не увидел .claude/: "
        f"{_returned_texts(events)[:800]}"
    )
