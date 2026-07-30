# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Addressivity — кому адресовано сообщение (BOB-023).

Боб в группе не должен встревать в каждый разговор. Этот чистый детектор
определяет, обращено ли сообщение **к Бобу**, **к другому участнику** или **ни к
кому** (общее/риторическое), опираясь на сигналы Telegram, уже извлечённые
gateway'ем (reply-to / @mention / текст) — без I/O, без рандома, детерминированно.
Над ним в application живёт политика отклика (вступить / лайкнуть / промолчать);
сам детектор — perception, а не решение.

* :class:`Addressivity` — DIRECTED_TO_BOB / DIRECTED_TO_OTHER / AMBIENT.
* :func:`classify_addressivity` — чистое отображение сигналов на адресность.
* :func:`others_present` — лёгкая эвристика «в недавней истории есть НЕ текущий
  собеседник» (то есть тред не 1:1), нужная политике AMBIENT.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "Addressivity",
    "AddressivityThresholds",
    "ResponseOutcome",
    "classify_addressivity",
    "decide_response",
    "others_present",
]

# Имена-обращения к Бобу (в ЛЮБОЙ позиции реплики, регистронезависимо). Лёгкая
# эвристика: именно ОБРАЩЕНИЕ-вокатив («…, Боб, …»), поэтому за именем должен вплотную
# следовать терминатор-обращения — «Боб классный»/«Бобу» это про Боба, а не к нему.
# Кириллические look-alikes намеренны.
_BOB_NAMES: tuple[str, ...] = ("боб", "bob")

# Терминаторы-обращения ВПЛОТНУЮ за именем: «,»/«:» (разделитель-обращение) плюс
# «!»/«?» — «Боб!»/«Боб?» это оклик. Тире «-»/«—» ВПЛОТНУЮ за именем НАМЕРЕННО не
# входит: «Боб-строитель»/«Боб—робот» («Bob is a robot») — 3-е лицо/композит, а не
# обращение; настоящий оклик через тире идёт С ПРОБЕЛОМ («эй Боб - ты тут?»), где
# справа от имени пробел, а не тире вплотную (BOB-069.6). Конец строки — тоже
# терминатор, но лишь когда слева есть непробельный address-контекст (трейлинг-вокатив
# «…, Боб»), иначе одинокое «Боб» читалось бы как оклик.
_ADDRESS_TERMINATORS: frozenset[str] = frozenset({",", ":", "!", "?"})

# Метка реплики самого Боба в истории: реплика Боба никогда не считается сторонним
# собеседником в others_present. _sender_label режет запись по первому ": ", поэтому
# метка приходит БЕЗ двоеточия — сравниваем с "bob" (запись вида "bob: ..." дала бы
# метку "bob"; в штатном формате "<sender>: <text>\nbob: <reply>" метка — <sender>).
_BOB_TURN_PREFIX = "bob"

# Разделитель между меткой отправителя и текстом в истории ("<sender>: <text>…").
_SENDER_LABEL_SEPARATOR = ": "


class Addressivity(Enum):
    """Кому адресовано сообщение в треде (perception, не решение).

    * :data:`DIRECTED_TO_BOB` — обращено к Бобу (mention / reply на Боба /
      имя-обращение «Боб, …»). Боб всегда вступает.
    * :data:`DIRECTED_TO_OTHER` — обращено к другому участнику (reply на чужое
      сообщение / обращение к другому). По умолчанию Боб не лезет.
    * :data:`AMBIENT` — ни к кому конкретно: общее, риторическое, «в воздух».
    """

    DIRECTED_TO_BOB = "directed_to_bob"
    DIRECTED_TO_OTHER = "directed_to_other"
    AMBIENT = "ambient"


def classify_addressivity(
    *,
    text: str | None,
    mentions_bob: bool,
    reply_to_sender_id: int | None,
    bob_user_id: int | None,
    others_present: bool,
) -> Addressivity:
    """Определить адресность сообщения — чисто и детерминированно (BOB-023).

    Приоритет сигналов (сильный → слабый):

    1. **DIRECTED_TO_BOB**, если ``mentions_bob`` ИЛИ это reply на сообщение Боба
       (``bob_user_id`` известен и ``reply_to_sender_id == bob_user_id``) ИЛИ в
       начале текста имя-обращение к Бобу («Боб, …»). Прямое обращение всегда
       перевешивает — Боб никогда не игнорирует адресованное ему.
    2. **DIRECTED_TO_OTHER**, если это reply на сообщение ДРУГОГО человека
       (``reply_to_sender_id`` задан и не равен Бобу — в том числе когда identity
       Боба ещё не резолвнута: тогда любой reply-target трактуется как «не Боб»,
       а mention выше всё равно поймал бы прямое обращение).
    3. **AMBIENT** иначе — ни reply, ни mention, ни имя-обращение.

    ``others_present`` здесь не влияет на классификацию (его читает политика
    отклика для AMBIENT); он в сигнатуре, чтобы вызов был единообразным.
    """
    del others_present  # читается политикой, не самим детектором
    if mentions_bob or _is_reply_to_bob(reply_to_sender_id, bob_user_id):
        return Addressivity.DIRECTED_TO_BOB
    if _is_name_address_to_bob(text):
        return Addressivity.DIRECTED_TO_BOB
    if reply_to_sender_id is not None:
        # Reply на чужое сообщение (не Боба — иначе ветка выше уже сработала).
        return Addressivity.DIRECTED_TO_OTHER
    return Addressivity.AMBIENT


def _is_reply_to_bob(reply_to_sender_id: int | None, bob_user_id: int | None) -> bool:
    """Является ли сообщение реплаем на сообщение Боба (нужна известная identity)."""
    return (
        bob_user_id is not None
        and reply_to_sender_id is not None
        and reply_to_sender_id == bob_user_id
    )


def _is_name_address_to_bob(text: str | None) -> bool:
    """Есть ли в тексте вокатив-обращение по имени к Бобу («…, Боб, …»), регистронезав.

    Вокатив «Боб» в ЛЮБОЙ позиции считается обращением (BOB-069.A), если выполнены оба
    условия:

    * слева от имени — граница слова: начало строки, пробел или разделитель (не
      середина слова — «робобот»/«超Боб»/«пробоб» не в счёт);
    * справа ВПЛОТНУЮ — терминатор-обращения (:data:`_ADDRESS_TERMINATORS`: «,» / «:» /
      «!» / «?»; тире «-»/«—» вплотную НЕ считается — это композит «Боб-строитель»),
      ЛИБО конец строки при наличии непробельного address-контекста слева
      (трейлинг-вокатив «…, Боб»).

    Так «Кстати, Боб, расскажи» и «эй Боб!» — обращение, а «Бобу»/«Боба»/«Боб молодец»
    (за именем буква или пробел+слово, а не терминатор) и «Боб-строитель» (тире вплотную)
    — нет (AMBIENT). Одинокое «Боб» (с ведущими пробелами или без) тоже AMBIENT.
    """
    if not text:
        return False
    lowered = text.casefold()
    length = len(lowered)
    for name in _BOB_NAMES:
        found = lowered.find(name)
        while found != -1:
            if _is_vocative_at(lowered, found, len(name), length):
                return True
            found = lowered.find(name, found + 1)
    return False


def _is_vocative_at(lowered: str, start: int, name_len: int, length: int) -> bool:
    """Является ли вхождение имени в позиции ``start`` вокативом-обращением к Бобу."""
    if not _has_left_word_boundary(lowered, start):
        return False
    after = start + name_len
    if after == length:
        # Конец строки — вокатив лишь при РЕАЛЬНОМ address-контексте слева
        # (непробельный текст: «…, Боб»), а не при одном ведущем пробеле. Иначе « Боб»
        # (голое имя с ведущими пробелами) ложно читалось бы как трейлинг-вокатив,
        # хотя семантически это то же одинокое «Боб» → AMBIENT (BOB-069.6).
        return _has_left_address_context(lowered, start)
    return lowered[after] in _ADDRESS_TERMINATORS


def _has_left_word_boundary(lowered: str, start: int) -> bool:
    """Есть ли слева от имени граница слова (начало строки / не буква-цифра)."""
    return start == 0 or not lowered[start - 1].isalnum()


def _has_left_address_context(lowered: str, start: int) -> bool:
    """Есть ли слева от имени непробельный address-контекст (не только ведущий пробел)."""
    return bool(lowered[:start].strip())


def others_present(
    history: Iterable[str], *, current_sender_name: str | None
) -> bool:
    """Есть ли в недавней истории треда НЕ текущий собеседник (тред не 1:1) (BOB-023).

    Лёгкая, заземлённая эвристика поверх уже реплеенной истории: каждая запись имеет
    форму ``"<sender>: <text>\\nbob: <reply>"``; берём метку отправителя пользователя
    и считаем «другой кто-то присутствует», если хотя бы одна метка — не реплика
    Боба и не совпадает с именем текущего собеседника. В личном 1:1 owner<->Bob все
    метки совпадают с текущим именем → ``False`` (его пространство, Боб вступает);
    появился третий участник → ``True`` (чаще промолчать/лайкнуть). Без имени
    текущего собеседника любая сторонняя реплика читается как присутствие другого.
    """
    current = current_sender_name.casefold() if current_sender_name else None
    for entry in history:
        label = _sender_label(entry)
        if label is None:
            continue
        if label.casefold() == _BOB_TURN_PREFIX:
            continue
        if current is None or label.casefold() != current.casefold():
            return True
    return False


def _sender_label(entry: str) -> str | None:
    """Метка отправителя пользователя из записи истории ("<sender>: <text>…"), или None."""
    head, sep, _rest = entry.partition(_SENDER_LABEL_SEPARATOR)
    if not sep:
        return None
    return head


# --- Политика отклика (perception → исход) -----------------------------------

# Консервативные значения по умолчанию. ``barge_in_interest`` — высокий порог
# интереса, чтобы ИЗРЕДКА вклиниться в ЧУЖОЙ диалог (DIRECTED_TO_OTHER); он выше
# ``ambient_interest`` — порога, чтобы вступить в общий ambient при других. Частоты
# малы и seeded: ``barge_in_freq`` (вклиниться в чужое) меньше или равна
# ``ambient_barge_in_freq`` (вступить в общий ambient — присоединиться легче).
# ``react_chance`` — насколько часто «прочитал общее» оборачивается лайк-реакцией
# вместо полного молчания (тёплый знак присутствия, без перехвата).
_DEFAULT_BARGE_IN_INTEREST = 0.8
_DEFAULT_AMBIENT_INTEREST = 0.6
_DEFAULT_BARGE_IN_FREQ = 0.05
_DEFAULT_AMBIENT_BARGE_IN_FREQ = 0.15
_DEFAULT_REACT_CHANCE = 0.3


class ResponseOutcome(Enum):
    """Что Боб делает с этим ходом по адресности (политика над детектором).

    * :data:`ENGAGE` — вступает: дальше форму решают engagement/REACT_ONLY как
      прежде (полный ответ или терс-ответ).
    * :data:`REACT` — молча ставит лайк-реакцию (переиспользует REACT_ONLY-путь):
      прочитал, отметил присутствие, но не вступает словами.
    * :data:`SILENT` — промолчал: прочитал, не счёл стоящим — ранний выход без
      ответа и без реакции.
    """

    ENGAGE = "engage"
    REACT = "react"
    SILENT = "silent"


@dataclass(frozen=True, slots=True)
class AddressivityThresholds:
    """Тюнинг политики отклика (инъекция из ``addressivity.*`` конфига).

    ``barge_in_interest`` — высокий порог интереса, чтобы вклиниться в ЧУЖОЙ диалог
    (DIRECTED_TO_OTHER); ``ambient_interest`` — порог, чтобы вступить в общий ambient
    при других участниках (ниже первого). ``barge_in_freq`` — малая seeded-частота
    вклинивания в чужое; ``ambient_barge_in_freq`` — частота вступления в общий
    ambient (присоединиться легче, поэтому ≥). ``react_chance`` — доля ambient-ходов
    при других, где Боб ставит лайк-реакцию вместо полного молчания. Значения по
    умолчанию консервативны: в чужой разговор Боб почти не лезет.
    """

    barge_in_interest: float = _DEFAULT_BARGE_IN_INTEREST
    ambient_interest: float = _DEFAULT_AMBIENT_INTEREST
    barge_in_freq: float = _DEFAULT_BARGE_IN_FREQ
    ambient_barge_in_freq: float = _DEFAULT_AMBIENT_BARGE_IN_FREQ
    react_chance: float = _DEFAULT_REACT_CHANCE


def decide_response(
    addressivity: Addressivity,
    *,
    interest: float,
    others_present: bool,
    roll: float,
    thresholds: AddressivityThresholds | None = None,
) -> ResponseOutcome:
    """Решить исход хода по адресности — чисто, детерминированно по ``roll`` (BOB-023).

    ``roll`` — одна seeded-проба в ``[0, 1)`` (инъектируется application'ом из общего
    RNG, чтобы ход воспроизводился). ``interest`` — насколько тема интересна Бобу
    (``[0, 1]``, из аппетита .2a). Политика:

    * **DIRECTED_TO_BOB** → всегда :data:`~ResponseOutcome.ENGAGE` (никогда SILENT) —
      прямое обращение не игнорируется.
    * **DIRECTED_TO_OTHER** → :data:`~ResponseOutcome.SILENT` по умолчанию (не лезет в
      чужой 1:1); ИЗРЕДКА вклинивается, только если ``interest`` берёт ВЫСОКИЙ порог
      ``barge_in_interest`` И редкий ``roll`` ниже ``barge_in_freq``. Не перехватывает.
    * **AMBIENT** в 1:1 (``not others_present``) → :data:`~ResponseOutcome.ENGAGE` (его
      пространство). С другими — чаще :data:`~ResponseOutcome.SILENT` или
      :data:`~ResponseOutcome.REACT` (лайк), а при высоком интересе и удачном (более
      частом, чем для чужого диалога) ``roll`` — :data:`~ResponseOutcome.ENGAGE`.
    """
    bands = thresholds if thresholds is not None else AddressivityThresholds()
    if addressivity is Addressivity.DIRECTED_TO_BOB:
        return ResponseOutcome.ENGAGE
    if addressivity is Addressivity.DIRECTED_TO_OTHER:
        barge_in = interest >= bands.barge_in_interest and roll < bands.barge_in_freq
        return ResponseOutcome.ENGAGE if barge_in else ResponseOutcome.SILENT
    return _decide_ambient(
        interest=interest, others_present=others_present, roll=roll, bands=bands
    )


def _decide_ambient(
    *,
    interest: float,
    others_present: bool,
    roll: float,
    bands: AddressivityThresholds,
) -> ResponseOutcome:
    """Решить исход AMBIENT-хода: 1:1 — вступает; с другими — молчит/лайк/изредка втягивает.

    В 1:1 (``not others_present``) ambient это пространство Боба → ENGAGE. С другими он
    чаще не вступает словами: при высоком интересе и удачном (более частом, чем для
    чужого диалога) ``roll`` — ENGAGE; иначе тёплый лайк присутствия (REACT) или полное
    молчание (SILENT), форму решает та же одна проба ``roll``.
    """
    if not others_present:
        return ResponseOutcome.ENGAGE
    if interest >= bands.ambient_interest and roll < bands.ambient_barge_in_freq:
        return ResponseOutcome.ENGAGE
    if roll < bands.ambient_barge_in_freq + bands.react_chance:
        return ResponseOutcome.REACT
    return ResponseOutcome.SILENT
