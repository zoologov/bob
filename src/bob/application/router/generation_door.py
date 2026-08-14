# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=router

"""Двери генерации: какие бывают виды работы LLM и чем является вывод каждой (BOB-096.3).

Одна дверь генерации — это один вид работы, который Боб отдаёт модели. До этого среза
двери различались только тем, на какой тир их отправить, и все прочие решения о них
принимались по одному частному признаку (``task_type is REPLY_TO_USER``). Так и вышел
дефект bob-alr.12: запрет отыгрывать GUPPI был приклеен ровно к ОДНОЙ двери —
разговорному ходу, — а рефлексия, переоценка, консолидация, проактивная реплика,
work_journal и ``extract_facts`` его не видели. Их вывод ложится в память, память
возвращается в ход припоминанием, и Боб добросовестно подражает собственным нарушениям
канона (механизм BOB-074: отравление бьёт по ПОВЕДЕНИЮ, а не только по тону). Живое:
«GUPPI уже проверил все связи. Он ГОВОРИТ, что стрелочки идут именно туда».

Поэтому у двери теперь названы её свойства — независимые ФАКТЫ о выводе, а не ярлык:

* :attr:`GenerationDoor.speaks_as_bob` — вывод уходит к человеку или в запись КАК СЛОВА
  БОБА (разговорный ход, проактивная реплика, рефлексия, правило-поправка), а не как
  вердикт/метка/структура, которую никто никогда не прочтёт его голосом;
* :attr:`GenerationDoor.output_is_kept` — вывод ПЕРЕЖИВАЕТ ход: ложится в память
  (эпизод, факт, дайджест) или в другую долгую запись (правило, план, ``SOUL.md``), то
  есть завтра вернётся к модели как её собственный few-shot;
* :attr:`GenerationDoor.answers_in_machine_format` — ответ двери разбирается кодом (JSON,
  одно слово-метка), а не читается человеком. Свойство формы, а не смысла: запрет о
  голосе доезжает и до такой двери, но в формулировке, которая не зовёт в прозу.

Кому это нужно:

* :mod:`bob.application.router.voice_canon` — канон о голосе досылается двери, для которой
  ``speaks_as_bob or output_is_kept`` (:attr:`GenerationDoor.needs_voice_canon`);
* 🔴 вердикт «кто может говорить за Боба» (:mod:`bob.application.router.voice_integrity`)
  сегодня читает ``task_type is REPLY_TO_USER``; в терминах двери это
  ``speaks_as_bob and output_is_kept`` — «голос, который ОСТАЁТСЯ». Именно эта пара
  воспроизводит решение owner'а (BOB-087.E-M1): промежуточная строчка звучит голосом
  Боба, но не сохраняется и молча пропадает при сбое, поэтому дублёр ей допустим, а
  рефлексии и work_journal — уже нет.

🔴 **Разметка — это факт о ВЫЗЫВАЮЩЕМ, а не мнение о названии двери** (BOB-096.8). Первая
редакция реестра размечала часть дверей по предположению, и две оказались неверными:
«внутренний монолог» числился служебным, хотя третий его вызывающий (выбор увлечения)
клал ответ модели в SQLite и вплетал тему в реплики неделями, а «прочтение реакции» —
хотя оно ложится в эпизод и в стор заметных реакций. Обе разведены/переразмечены сверкой
ВСЕХ дверей с их настоящими вызывающими: кто зовёт и куда девается вывод. Поэтому у
каждой строки ниже стоит не ярлык, а причина; а появление у служебной двери НОВОГО
вызывающего краснеет отдельным гардом (``test_every_door_knows_who_calls_it``) — именно
так этот класс дефекта и возвращается.

🔴 Незнакомая дверь считается ГОЛОСОМ, КОТОРЫЙ ОСТАЁТСЯ (:data:`UNCLASSIFIED_DOOR`) —
fail-closed, как неизвестная дверь в следе материала хода (BOB-090.B-fix2). Молчаливое
выпадение из-под запрета — это и есть чинимый дефект, поэтому цена ошибки платится в
сторону лишнего канона, а не потерянного. Полноту таблицы стережёт архитектурный тест:
новый вид работы обязан назвать, чем является его вывод.

Чистый модуль: словарь и три предиката, ни I/O, ни состояния.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "UNCLASSIFIED_DOOR",
    "GenerationDoor",
    "TaskType",
    "door_for",
]


class TaskType(Enum):
    """Kinds of LLM work, each mapped to a preferred tier by the router."""

    REPLY_TO_USER = "reply_to_user"
    GENESIS = "genesis"
    SENTIMENT = "sentiment"
    INNER_MONOLOGUE = "inner_monologue"
    REFLECT = "reflect"
    EXTRACT_FACTS = "extract_facts"
    PLAN_GOAL = "plan_goal"
    DETECT_PATTERNS = "detect_patterns"
    CODING_INTENT = "coding_intent"
    RESPONSE_JUDGE = "response_judge"
    REACTION_JUDGE = "reaction_judge"
    PRIVILEGE_JUDGE = "privilege_judge"
    VOLATILITY_JUDGE = "volatility_judge"
    INTERIM_LINE = "interim_line"
    ROOM_READ = "room_read"
    STALENESS_JUDGE = "staleness_judge"
    DISCLOSURE_CONSENT = "disclosure_consent"
    WORK_JOURNAL = "work_journal"
    WORK_TALK = "work_talk"
    FASCINATION_PICK = "fascination_pick"


@dataclass(frozen=True, slots=True)
class GenerationDoor:
    """Чем является вывод одной двери генерации (три независимых факта)."""

    speaks_as_bob: bool
    output_is_kept: bool
    answers_in_machine_format: bool = False

    @property
    def needs_voice_canon(self) -> bool:
        """Нужен ли этой двери запрет о ГОЛОСЕ (отыгрыш GUPPI, речь и мнение за него).

        Достаточно ЛЮБОГО из двух: дверь говорит голосом Боба (тогда запрет — про саму
        реплику) или её вывод остаётся (тогда запрет — про будущий few-shot, который
        вернётся к модели припоминанием). Служебный вердикт, расходуемый в этом же ходе,
        канона не требует: он никого не учит говорить.
        """
        return self.speaks_as_bob or self.output_is_kept


# 🔴 Fail-closed для незнакомой двери: и голос, и долгая запись — то есть канон доедет.
# Проза, а не машинный формат: чужой JSON-контракт нам неизвестен, зато архитектурный
# тест краснеет в ту же секунду, так что до прода такая дверь не доживает.
UNCLASSIFIED_DOOR = GenerationDoor(speaks_as_bob=True, output_is_kept=True)

# Голос Боба, который остаётся: реплика публикуется как его слова и ложится в память.
_VOICE_THAT_STAYS = GenerationDoor(speaks_as_bob=True, output_is_kept=True)
# То же, но ответ разбирается кодом (JSON): канон доезжает в формуле без прозы.
_KEPT_VOICE_IN_MACHINE_FORMAT = GenerationDoor(
    speaks_as_bob=True, output_is_kept=True, answers_in_machine_format=True
)
# Вывод остаётся, но голосом Боба не звучит, и его разбирает код (JSON, метка, фраза).
_KEPT_RECORD_IN_MACHINE_FORMAT = GenerationDoor(
    speaks_as_bob=False, output_is_kept=True, answers_in_machine_format=True
)
# Служебный ход: вердикт/метка/классификация, расходуемая в этом же ходе.
_SERVICE = GenerationDoor(speaks_as_bob=False, output_is_kept=False)

_DOORS: dict[TaskType, GenerationDoor] = {
    # Разговорный ход — и проактивная реплика, которая ходит той же дверью: текст уходит
    # человеку как слова Боба и сохраняется эпизодом.
    TaskType.REPLY_TO_USER: _VOICE_THAT_STAYS,
    # Пробуждение: нарратив от первого лица + профиль личности, навсегда в SOUL.md и
    # genesis_log. Ответ — строгий JSON.
    TaskType.GENESIS: _KEPT_VOICE_IN_MACHINE_FORMAT,
    # Три двери одного вида: рефлексия (heartbeat), её переоценка и дайджест
    # консолидации. Все три пишут в episodic_log — главный источник отравления.
    TaskType.REFLECT: _VOICE_THAT_STAYS,
    # Дневник работы: 1-3 эпизода 'work' от первого лица.
    TaskType.WORK_JOURNAL: _VOICE_THAT_STAYS,
    # Выжимка фактов: голосом Боба не говорит, но ложится в semantic_memory и
    # возвращается припоминанием. Ответ — JSON-массив.
    TaskType.EXTRACT_FACTS: _KEPT_RECORD_IN_MACHINE_FORMAT,
    # 🔴 Выбор увлечения (BOB-096.8, ревью MAJOR-2). Ходил дверью «внутренний монолог» —
    # то есть считался служебным, — но ``EvolveFascination._tier0_pick`` кладёт ответ
    # модели в ``fascination_store`` (SQLite), откуда тема НЕДЕЛЯМИ вплетается в контекст
    # ответа и звучит как «меня сейчас занимает…»: это и долгая запись, и слова Боба о
    # себе. Ответ разбирает код (первая строка = именная фраза), поэтому машинная форма:
    # полная проза о речи сбила бы дешёвую модель с формата ответа.
    TaskType.FASCINATION_PICK: _KEPT_VOICE_IN_MACHINE_FORMAT,
    # 🔴 Прочтение реакции (BOB-096.8, та же сверка). Тоже числилось служебным, но
    # ``PerceiveReaction`` вплетает ``ReactionMeaning.interpretation`` в эпизод «X
    # отреагировал 👍 на моё «…» — <прочтение>» и в стор заметных реакций, откуда оно
    # возвращается припоминанием. Голосом Боба дверь не говорит (её ответ разбирает код),
    # но «вывод остаётся» — как у выжимки фактов, и этого достаточно для канона.
    TaskType.REACTION_JUDGE: _KEPT_RECORD_IN_MACHINE_FORMAT,
    # Правило-поправка: наблюдение и поправка звучат голосом Боба (срез 5 их озвучивает)
    # и хранятся в self-improvement. Ответ — JSON-массив.
    TaskType.DETECT_PATTERNS: _KEPT_VOICE_IN_MACHINE_FORMAT,
    # План цели: задачи сохраняются в граф целей, но это служебная структура для апрува
    # owner'ом, не речь Боба. Ответ — JSON.
    TaskType.PLAN_GOAL: _KEPT_RECORD_IN_MACHINE_FORMAT,
    # Промежуточная строчка «секунду, гляну» — публикуется в чате как реплика Боба
    # (значит, канон ей нужен), но нигде не сохраняется и при сбое молча пропадает,
    # поэтому «голосом, который остаётся», не является (решение owner'а, BOB-087.E-M1).
    TaskType.INTERIM_LINE: GenerationDoor(speaks_as_bob=True, output_is_kept=False),
    # Приватная мысль (и гейт проактивности той же дверью): мысль превращается в дельту
    # настроения, вердикт гейта — в решение «заговаривать ли», и ни то ни другое никуда
    # не ложится. 🔴 Третий вызывающий — выбор увлечения — СОХРАНЯЛ вывод; он разведён в
    # свою дверь (BOB-096.8), потому и осталась правдой эта строка.
    TaskType.INNER_MONOLOGUE: _SERVICE,
    # Метка настроения текста: расходуется на шаг настроения этого же хода.
    TaskType.SENTIMENT: _SERVICE,
    # Одно слово coding/chat: решает, куда направить ход.
    TaskType.CODING_INTENT: _SERVICE,
    # Reply/react/ignore + эмодзи из проверенного набора: сама реплика рождается за
    # другой дверью, а «почему» уходит только в лог.
    TaskType.RESPONSE_JUDGE: _SERVICE,
    # Нужно ли разрешение владельца. 🔴 Пометка ``what`` ложится строкой запроса, но
    # НИКОГДА не читается обратно в промпт и не произносится (BOB-090.E) — это след, а не
    # материал речи. Начнут показывать или припоминать — дверь переезжает в «остаётся».
    TaskType.PRIVILEGE_JUDGE: _SERVICE,
    # Свежий ли факт нужен + поисковый запрос: расходуется на этот же поиск.
    TaskType.VOLATILITY_JUDGE: _SERVICE,
    # Как комната сдвинулась под черновиком: решение «отправлять ли», «почему» — в лог.
    TaskType.STALENESS_JUDGE: _SERVICE,
    # Разрешил ли владелец огласить приватное: булев вердикт этого хода.
    TaskType.DISCLOSURE_CONSENT: _SERVICE,
    # Чтение комнаты: ситуация/намерение/значимость нужны, чтобы решить, влезать ли;
    # сама реплика рождается за дверью разговорного хода, а текст чтения уходит в лог.
    TaskType.ROOM_READ: _SERVICE,
    # Про рабочее ли этот ход: одно слово, решает вес припоминания.
    TaskType.WORK_TALK: _SERVICE,
}


def door_for(task_type: TaskType) -> GenerationDoor:
    """Чем является вывод этой двери; незнакомая дверь — fail-closed (см. модуль)."""
    return _DOORS.get(task_type, UNCLASSIFIED_DOOR)
