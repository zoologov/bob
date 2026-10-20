# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты СЛЕДА материала хода (BOB-090.B-fix2, BLOCKER-1).

Дефект, ради которого след заведён: гейт переноса читал ОДНУ дверь — авто-recall,
снятый до генерации (``DeliveryScope.recalled``). А материал, который Боб добавляет от
себя, приходит к модели ещё как минимум тремя: выдачей ``search_memory`` /
``recall_memory`` в том же tool-loop, grounded-addon callback'ом и реплеем нити. Ревью
показало живой вызов: при пустом ``recalled`` текст с приватным содержанием уехал в
группу, согласия не спросили.

Лечение — не четвёртая проверка, а ОДИН след: всё, что попало в контекст хода,
отмечается меткой видимости и дверью, а гейт читает только его.

🔴 Свойство, которое здесь пинается: новая дверь не может добавиться МОЛЧА.

* дверь к ПАМЯТИ у Боба ровно одна — порт :class:`~bob.kernel.ports.MemoryRecall`, и
  :class:`MaterialTrailRecall` оборачивает его в ЕДИНСТВЕННОМ месте сборки, поэтому любой
  будущий потребитель порта попадает в след сам собой (и это стережёт архитектурный тест
  ниже);
* дверь НЕ к памяти обязана назвать себя новой :class:`MaterialOrigin`, а политика
  переноса перечисляет исключения списком — то есть неизвестная дверь считается
  переносимым материалом (fail-closed), а не тихо выпадает из гейта.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from bob.capabilities.usecases.turn_material import (
    MaterialOrigin,
    MaterialTrailRecall,
    TurnMaterial,
    armed_turn_material,
    current_turn_material,
)
from bob.social.disclosure import (
    VISIBILITY_OWNER_PRIVATE,
    VISIBILITY_PUBLIC,
    carries_owner_private,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.kernel.episode_types import Recalled

_PRIVATE = {"content": "личное", "visibility": VISIBILITY_OWNER_PRIVATE}
_PUBLIC = {"content": "общее", "visibility": VISIBILITY_PUBLIC}
_LEGACY = {"content": "старое"}  # NULL = public (BOB-051)


class _FakeRecall:
    """Порт памяти, который отдаёт заранее заданные попадания и считает вызовы."""

    def __init__(self, hits: Sequence[Mapping[str, object]]) -> None:
        self._hits = tuple(hits)
        self.calls: list[tuple[str, int, bool]] = []

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        self.calls.append((query, k, surface_old))
        return self._hits


def _private(material: TurnMaterial) -> bool:
    """Считает ли гейт переноса, что в следе есть переносимое приватное."""
    return carries_owner_private(material.transferable())


# --- Сам след: что в нём есть и чего в нём нет --------------------------------


def test_a_fresh_trail_carries_nothing_private() -> None:
    assert _private(TurnMaterial()) is False


def test_material_raised_by_memory_is_private_when_the_material_is() -> None:
    trail = TurnMaterial()
    trail.note((_PUBLIC, _PRIVATE), origin=MaterialOrigin.MEMORY)

    assert _private(trail) is True
    # 🔴 Дверь записывается ТОЧНО: перепутанная дверь увела бы материал в чужой пункт
    # политики — например в карве-аут живой нити, и гейт снова ослеп бы.
    assert trail.origins == frozenset({MaterialOrigin.MEMORY})


def test_a_ready_made_private_label_counts_the_same_as_a_recalled_item() -> None:
    # Метка может прийти и готовой (у нити нет своего поля ``visibility``) — она обязана
    # значить ровно то же самое, иначе дверь без поля стала бы дырой.
    trail = TurnMaterial()
    trail.note_visibility(VISIBILITY_OWNER_PRIVATE, origin=MaterialOrigin.MEMORY)

    assert _private(trail) is True


def test_public_material_from_memory_needs_no_consent() -> None:
    trail = TurnMaterial()
    trail.note((_PUBLIC, _LEGACY), origin=MaterialOrigin.MEMORY)

    assert _private(trail) is False


def test_the_live_thread_is_a_named_carve_out_not_a_transfer() -> None:
    # 🔴 Решение owner'а (B-fix): прямое распоряжение владельца — волеизъявление, а не
    # утечка. Ход в личке помечен приватным ЦЕЛИКОМ, и пока нить считалась переносом, Боб
    # отказывал владельцу в его же команде. Нить в следе ЕСТЬ (её видно), но переносом
    # она не считается — исключение названо, а не забыто.
    trail = TurnMaterial()
    trail.note_visibility(VISIBILITY_OWNER_PRIVATE, origin=MaterialOrigin.LIVE_THREAD)

    assert _private(trail) is False
    assert trail.origins == frozenset({MaterialOrigin.LIVE_THREAD})


def test_an_unknown_door_counts_as_transferable_material_by_default() -> None:
    # Fail-closed: политика перечисляет ИСКЛЮЧЕНИЯ, поэтому дверь, о которой политика не
    # знает, попадает под гейт, а не мимо него.
    carve_outs = {MaterialOrigin.LIVE_THREAD}
    for origin in MaterialOrigin:
        if origin in carve_outs:
            continue
        trail = TurnMaterial()
        trail.note((_PRIVATE,), origin=origin)
        assert _private(trail) is True, origin


def test_the_trail_stays_bounded_however_much_is_recalled() -> None:
    # След отвечает на вопрос «нёс ли ход приватное и откуда», а не хранит переписку:
    # содержимое в него не кладётся вовсе (и в ContextVar не оседает).
    trail = TurnMaterial()
    for index in range(500):
        trail.note(
            ({"content": f"эпизод {index}", "visibility": VISIBILITY_PUBLIC},),
            origin=MaterialOrigin.MEMORY,
        )

    assert len(trail.transferable()) == 1


def test_an_unarmed_turn_is_treated_as_possibly_private() -> None:
    # 🔴 Сомнение удерживает, а не выпускает (INV-8): если ход не армирован, следа нет —
    # и гейт обязан спросить согласие, а не пропустить молча. Пропуск был бы тихой дырой,
    # а лишний вопрос — заметен и безопасен.
    assert _private(current_turn_material()) is True
    # И «неизвестно» числится ПАМЯТЬЮ — дверью, которая под гейтом; повесь его на
    # карве-аут, и безопасное умолчание молча превратилось бы в пропуск.
    assert current_turn_material().origins == frozenset({MaterialOrigin.MEMORY})


def test_inside_an_armed_turn_the_trail_is_the_armed_one() -> None:
    with armed_turn_material() as trail:
        assert current_turn_material() is trail
        assert _private(trail) is False


def test_the_arming_is_released_even_when_the_turn_blows_up() -> None:
    class _BoomError(RuntimeError): ...

    try:
        with armed_turn_material():
            raise _BoomError
    except _BoomError:
        pass

    assert _private(current_turn_material()) is True  # снова «хода нет»


# --- Дверь памяти: декоратор порта --------------------------------------------


async def test_every_recall_through_the_port_lands_in_the_trail() -> None:
    inner = _FakeRecall((_PRIVATE,))
    recall = MaterialTrailRecall(inner)

    with armed_turn_material() as trail:
        hits = await recall.recall("что там было", k=5)

    assert tuple(hits) == (_PRIVATE,)  # выдача потребителю не изменилась
    assert _private(trail) is True
    assert trail.origins == frozenset({MaterialOrigin.MEMORY})


async def test_the_recall_contract_is_passed_through_untouched() -> None:
    inner = _FakeRecall(())
    recall = MaterialTrailRecall(inner)

    with armed_turn_material():
        await recall.recall("запрос", k=17, surface_old=True)

    assert inner.calls == [("запрос", 17, True)]


async def test_the_old_but_relevant_blend_stays_off_unless_asked() -> None:
    # Умолчание порта — «обычный recall»: декоратор не вправе сам просить у памяти
    # старое-но-релевантное, это отдельный, редкий и осознанный жест (BOB-021).
    inner = _FakeRecall(())

    await MaterialTrailRecall(inner).recall("запрос", k=3)

    assert inner.calls == [("запрос", 3, False)]


async def test_outside_a_turn_the_port_records_nothing_and_still_answers() -> None:
    # Проактивный тик и прочие неармированные пути: отправлять всё равно некому, а
    # писать в чужой след нельзя (ContextVar копируется по задаче).
    inner = _FakeRecall((_PRIVATE,))

    hits = await MaterialTrailRecall(inner).recall("вне хода", k=1)

    assert tuple(hits) == (_PRIVATE,)


async def test_a_second_door_through_the_same_port_is_recorded_too() -> None:
    # Ровно (a) и (b) из ревью: выдача memory-инструмента и addon-callback идут ЧЕРЕЗ
    # ТОТ ЖЕ порт, поэтому отдельного учёта им не нужно — они уже в следе.
    inner = _FakeRecall((_PUBLIC,))
    private_door = _FakeRecall((_PRIVATE,))

    with armed_turn_material() as trail:
        await MaterialTrailRecall(inner).recall("авто-recall", k=5)
        assert _private(trail) is False
        await MaterialTrailRecall(private_door).recall("поиск инструментом", k=8)

    assert _private(trail) is True


# --- Архитектурный гард: новая дверь не заведётся молча ------------------------

def _repo_src_root() -> Path:
    """Найти НАСТОЯЩЕЕ дерево исходников проекта (не установленный пакет).

    Гард сканирует репозиторий, а не то, что импортировалось: в песочнице мутационного
    прогона (``mutants/``) лежит частичная копия ``src``, и «прошёл, потому что файла нет»
    было бы вакуумной зелёнкой. Корень опознаётся по наличию самого сканируемого файла,
    поэтому найти не тот каталог нельзя, а не найти ни одного — ошибка, а не пропуск.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src" / "bob"
        if (candidate / "runtime" / "composition.py").is_file():
            return candidate
    raise AssertionError("дерево исходников проекта не найдено — гард нечего сканировать")


_SRC_ROOT = _repo_src_root()

# Настоящие ИСТОЧНИКИ recall (адаптеры над хранилищем). Всё остальное — декораторы
# ПОВЕРХ уже обёрнутого порта, и они след не обходят.
_RECALL_SOURCE = re.compile(r"\b(?:HybridMemoryRecall|Fts5MemoryRecall)\s*\(")

# Где источник вообще позволено конструировать: сам адаптер (Hybrid держит внутри
# keyword-ветку) и композиционный корень — единственная точка раздачи порта.
_ALLOWED_SOURCE_SITES = {
    "memory/adapters/hybrid_recall.py",
    "runtime/composition.py",
}


def _modules_constructing_a_recall_source() -> set[str]:
    return {
        path.relative_to(_SRC_ROOT).as_posix()
        for path in _SRC_ROOT.rglob("*.py")
        if _RECALL_SOURCE.search(path.read_text(encoding="utf-8"))
    }


def test_the_recall_port_is_built_in_one_place_only() -> None:
    # Если завтра кто-то соберёт себе собственный recall мимо корня, его дверь не попадёт
    # в след — и гейт переноса снова ослепнет на неё. Этот тест краснеет ровно тогда.
    assert _modules_constructing_a_recall_source() <= _ALLOWED_SOURCE_SITES


def test_the_composition_root_wraps_that_port_into_the_trail() -> None:
    # И ровно та единственная точка раздачи обёрнута следом — иначе весь гард выше
    # сторожил бы пустое место.
    source = (_SRC_ROOT / "runtime" / "composition.py").read_text(encoding="utf-8")

    assert re.search(r"MaterialTrailRecall\(\s*HybridMemoryRecall\(", source)
