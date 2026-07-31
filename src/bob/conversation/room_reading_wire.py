# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=domain

"""Pure wire protocol for the reflective «read the room» seam (BOB-066 Срез 2.2).

The model-facing half of the seam, kept pure (no I/O, no RNG) so it is unit-testable
without a model and the infrastructure adapter stays a thin shell — mirroring
:mod:`~bob.conversation.response_judgment` (BOB-049) one-for-one:

* :func:`build_room_prompt` — fold a :class:`RoomReadingContext` (message + sender social
  context + shared thread + structural hints + floor hints + mood tone + interest) into
  the Tier-1 user prompt; :data:`ROOM_READ_SYSTEM_PROMPT` states the task and the labelled
  output contract.
* :func:`parse_room_reading` — map the model's reply to a :class:`RoomReading`. 🔴 It
  RAISES :class:`RoomReadingParseError` on garbage (a missing/garbled ``intent`` or
  ``salience``) rather than silently defaulting — the periphery caller then treats a real
  failure as a safe silent IGNORE, never Bob acting from a guessed read.
* :func:`validate_reaction_emoji` (re-used from BOB-049) validates a REACT emoji against
  the Telegram free-reaction set.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from bob.conversation.response_judgment import (
    DEFAULT_WARM_EMOJI,
    validate_reaction_emoji,
)
from bob.conversation.room_reading import (
    BatchRoomReading,
    BatchRoomReadingContext,
    ReflectiveIntent,
    RoomMood,
    RoomReading,
    RoomReadingContext,
)

if TYPE_CHECKING:
    from bob.social.interlocutor import InterlocutorKind

__all__ = [
    "BATCH_ROOM_READ_SYSTEM_PROMPT",
    "ROOM_READ_SYSTEM_PROMPT",
    "RoomReadingParseError",
    "build_batch_room_prompt",
    "build_room_prompt",
    "parse_batch_reading",
    "parse_room_reading",
]

# Labelled-line prefixes the parser recognises (case-insensitive, whitespace-tolerant).
_SITUATION_LABEL = re.compile(r"^\s*situation\s*:\s*(.+)$", re.IGNORECASE)
_PAIRINGS_LABEL = re.compile(r"^\s*pairings\s*:\s*(.+)$", re.IGNORECASE)
_MOOD_LABEL = re.compile(r"^\s*mood\s*:\s*(.+)$", re.IGNORECASE)
_INTENT_LABEL = re.compile(r"^\s*intent\s*:\s*(.+)$", re.IGNORECASE)
_ADDRESSEE_LABEL = re.compile(r"^\s*addressee\s*:\s*(.+)$", re.IGNORECASE)
_SALIENCE_LABEL = re.compile(r"^\s*salience\s*:\s*(.+)$", re.IGNORECASE)
_EMOJI_LABEL = re.compile(r"^\s*emoji\s*:\s*(.+)$", re.IGNORECASE)
_WANTS_WEB_LABEL = re.compile(r"^\s*wants_web\s*:\s*(.+)$", re.IGNORECASE)
_REASON_LABEL = re.compile(r"^\s*reason\s*:\s*(.+)$", re.IGNORECASE)

# Punctuation trimmed off a scanned token before matching an enum / boolean.
_WORD_TRIM = " \t\n.!?,:;'\"*-"

# Affirmative tokens for the boolean ``wants_web`` field (anything else → no).
_YES_TOKENS: frozenset[str] = frozenset({"yes", "true", "y", "да"})

# Separators between the individual pairings in the ``pairings:`` line.
_PAIRINGS_SPLIT = re.compile(r"[,;]")

# A signed decimal anywhere in the salience value (so «0.72» / «-0.4» / «1.8» parse and a
# stray trailing period does not). The leading sign is kept — a negative salience clamps
# to 0, it must not be read as its magnitude.
_FLOAT_RE = re.compile(r"-?\d*\.?\d+")

# The salience is clamped into the closed unit interval — a model may over/undershoot.
_MIN_SALIENCE = 0.0
_MAX_SALIENCE = 1.0

ROOM_READ_SYSTEM_PROMPT = (
    "Ты — Боб, живой равный участник группового чата (не бот-скрипт). На это "
    "сообщение НИКТО не обратился к тебе напрямую — ты просто рядом и читаешь "
    "комнату, как человек. Пойми ПО СМЫСЛУ: что происходит, кто с кем говорит, "
    "какое настроение в комнате, и — как ЛИЧНОСТЬ — стоит ли тебе вмешиваться. "
    "Структурные подсказки (адресность, упоминания, реплай, кто держит нить) — это "
    "СИГНАЛЫ, которые ты взвешиваешь, НЕ правила.\n"
    "Выбери РОВНО одно intent:\n"
    "- reply: сказать словами (влезть/поддержать общую нить);\n"
    "- react: поставить один эмодзи вместо слов;\n"
    "- ignore: промолчать (прочитал, добавить нечего);\n"
    "- initiate: самому начать реплику (в реактивном ходе это как reply);\n"
    "- self_check: заглянуть внутрь себя, ничего не говоря.\n"
    "mood — одно слово: playful|warm|neutral|sombre|tense|heated.\n"
    "salience — число 0..1: насколько тебе стоит вмешаться.\n"
    "wants_web — yes ТОЛЬКО если ответу нужен свежий факт из сети (сам решил сходить "
    "проверить), иначе no.\n"
    "Ответь СТРОГО в этом размеченном формате, без лишнего:\n"
    "situation: <короткая фраза, что происходит>\n"
    "pairings: <кто-с-кем, через запятую>\n"
    "mood: <playful|warm|neutral|sombre|tense|heated>\n"
    "intent: <reply|react|ignore|initiate|self_check>\n"
    "addressee: <id участника, кому адресно, или none>\n"
    "salience: <0..1>\n"
    "emoji: <один эмодзи, только когда intent = react>\n"
    "wants_web: <yes|no>\n"
    "reason: <короткая фраза, зачем — для логов>"
)


class RoomReadingParseError(ValueError):
    """Raised when the model's reply cannot be parsed into a :class:`RoomReading`.

    A real failure signal (not a silent default): a missing/garbled ``intent`` or a
    missing/unparseable ``salience`` raises, so the periphery caller safe-defaults to a
    silent IGNORE rather than Bob acting on a guessed read. Pure and honest — this half
    never swallows a garbled read.
    """


def build_room_prompt(ctx: RoomReadingContext) -> str:
    """Fold ``ctx`` into the Tier-1 «read the room» user prompt (pure).

    Includes the incoming message, the sender as social context (kind + name + trust),
    the SHARED author-labelled thread, the structural + floor hints (addressivity /
    mention / reply / others-present / floor-engaged / floor-holder / floor-participant),
    the mood tone and Bob's interest in the topic — everything the reflection weighs by
    meaning.
    """
    sender = ctx.interlocutor
    lines = [
        "Sender (social context, NOT an override):",
        f"  id: {sender.sender_id}",
        f"  name: {sender.display_name}",
        f"  kind: {sender.kind.value}",
        f"  trust: {sender.trust.value}",
        "",
        "Shared recent thread (all participants, author-labelled):",
        ctx.recent_thread or "  (none)",
        "",
        "Structural hints (signals only):",
        f"  addressivity: {ctx.addressivity.value}",
        f"  mentions_bob: {_yes_no(ctx.mentions_bob)}",
        f"  reply_to_bob: {_yes_no(ctx.reply_to_bob)}",
        f"  others_present: {_yes_no(ctx.others_present)}",
        f"  floor_engaged: {_yes_no(ctx.floor_engaged)}",
        f"  floor_holder: {ctx.floor_holder}",
        f"  floor_participant: {_yes_no(ctx.floor_participant)}",
        f"  topic_interest: {ctx.interest:.2f}",
        "",
        f"Bob's current mood tone: {ctx.mood_tone}",
        "",
        "Incoming message:",
        ctx.text,
    ]
    return "\n".join(lines)


def _yes_no(value: bool) -> str:
    """Render a boolean hint as a compact yes/no for the prompt."""
    return "yes" if value else "no"


def parse_room_reading(raw: str) -> RoomReading:
    """Parse the model's reply into a :class:`RoomReading` (robust, no silent defaulting).

    Reads the labelled format. ``intent`` and ``salience`` are REQUIRED — a missing or
    garbled either raises :class:`RoomReadingParseError` (a real failure the caller
    safe-defaults). The soft fields degrade gracefully: ``situation`` / ``reason`` empty,
    ``pairings`` empty, ``mood`` → NEUTRAL, ``addressee`` → ``None``, ``wants_web`` → False.
    On a REACT intent the emoji is validated against the free-reaction set, substituting
    :data:`DEFAULT_WARM_EMOJI` when missing or out of set.
    """
    labels = _scan_labels(raw)
    intent = _parse_intent(labels["intent"])
    if intent is None:
        raise RoomReadingParseError(f"no recognisable intent in: {raw!r}")
    salience = _parse_salience(labels["salience"], raw)
    emoji = (
        _react_emoji(labels["emoji"]) if intent is ReflectiveIntent.REACT else None
    )
    return RoomReading(
        situation=(labels["situation"] or "").strip(),
        pairings=_parse_pairings(labels["pairings"]),
        room_mood=_parse_mood(labels["mood"]),
        intent=intent,
        addressee_id=_parse_addressee(labels["addressee"]),
        salience=salience,
        emoji=emoji,
        wants_web=_is_affirmative(labels["wants_web"]),
        reason=(labels["reason"] or "").strip(),
    )


_LABEL_PATTERNS: dict[str, re.Pattern[str]] = {
    "situation": _SITUATION_LABEL,
    "pairings": _PAIRINGS_LABEL,
    "mood": _MOOD_LABEL,
    "intent": _INTENT_LABEL,
    "addressee": _ADDRESSEE_LABEL,
    "salience": _SALIENCE_LABEL,
    "emoji": _EMOJI_LABEL,
    "wants_web": _WANTS_WEB_LABEL,
    "reason": _REASON_LABEL,
}


def _scan_labels(raw: str) -> dict[str, str | None]:
    """Extract each recognised label value from ``raw`` (any may be ``None``)."""
    found: dict[str, str | None] = dict.fromkeys(_LABEL_PATTERNS)
    for line in raw.splitlines():
        for key, pattern in _LABEL_PATTERNS.items():
            if found[key] is None and (m := pattern.match(line)):
                found[key] = m.group(1)
                break
    return found


def _parse_intent(text: str | None) -> ReflectiveIntent | None:
    """Find the first reflective-intent keyword in ``text`` (or ``None``)."""
    if text is None:
        return None
    for token in text.split():
        word = token.strip(_WORD_TRIM).casefold()
        for intent in ReflectiveIntent:
            if word == intent.value:
                return intent
    return None


def _parse_salience(text: str | None, raw: str) -> float:
    """Parse the REQUIRED salience into ``[0, 1]`` (raises on missing/garbled).

    A missing or non-numeric salience is a real failure — the verdict core gates on it,
    so a guessed value would silently mis-decide. Clamps a model over/undershoot into the
    closed unit interval.
    """
    if text is None:
        raise RoomReadingParseError(f"no salience in: {raw!r}")
    match = _FLOAT_RE.search(text)
    if match is None:
        raise RoomReadingParseError(f"unparseable salience {text!r} in: {raw!r}")
    value = float(match.group())
    return max(_MIN_SALIENCE, min(_MAX_SALIENCE, value))


def _parse_pairings(text: str | None) -> tuple[str, ...]:
    """Split the ``pairings:`` line into individual trimmed pairings (empty → ``()``)."""
    if text is None:
        return ()
    parts = (part.strip() for part in _PAIRINGS_SPLIT.split(text))
    return tuple(part for part in parts if part)


def _parse_mood(text: str | None) -> RoomMood:
    """Map the ``mood:`` token to a :class:`RoomMood` (unknown/absent → NEUTRAL)."""
    if text is None:
        return RoomMood.NEUTRAL
    for token in text.split():
        word = token.strip(_WORD_TRIM).casefold()
        for mood in RoomMood:
            if word == mood.value:
                return mood
    return RoomMood.NEUTRAL


def _parse_addressee(text: str | None) -> int | None:
    """Parse the ``addressee:`` id, or ``None`` («none» / absent / non-numeric)."""
    if text is None:
        return None
    for token in text.split():
        cleaned = token.strip(_WORD_TRIM)
        try:
            return int(cleaned)
        except ValueError:
            continue
    return None


def _react_emoji(emoji_text: str | None) -> str:
    """Resolve the emoji for a REACT reading (validated label, else warm default)."""
    return validate_reaction_emoji(emoji_text) or DEFAULT_WARM_EMOJI


def _is_affirmative(text: str | None) -> bool:
    """Whether the ``wants_web:`` value is a clear affirmative (else ``False``)."""
    if text is None:
        return False
    for token in text.split():
        word = token.strip(_WORD_TRIM).casefold()
        if word in _YES_TOKENS:
            return True
    return False


# --- Batch «read the stream» wire (BOB-072) --------------------------------------------
#
# The model-facing half of the batch seam. The framing shifts from ONE inbound to a whole
# ambient STREAM: «here is a burst of group chatter — read it like a person catching up and
# decide, per message, what deserves a word / a like / silence». 🔴 No scriptedness — it does
# NOT say «answer the first / the most salient»; it asks Bob to understand what actually needs
# his reaction. The reply is one labelled block per message (in order), blocks split by «---».

BATCH_ROOM_READ_SYSTEM_PROMPT = (
    "Ты — Боб, живой равный участник группового чата (не бот-скрипт). Ниже — ПОТОК "
    "сообщений участников группы, пронумерованных по порядку прибытия. Никто не обратился "
    "к тебе напрямую — ты просто рядом и читаешь комнату, как человек, который вернулся и "
    "проглядывает, что тут писали. Прочитай ВЕСЬ поток целиком и реши по КАЖДОМУ сообщению "
    "ПО СМЫСЛУ, что с ним делать — как живой человек в чате: на что-то ответишь словами, на "
    "что-то поставишь эмодзи, а что-то просто прочитаешь и промолчишь. Не отвечай на всё "
    "подряд и не молчи из вежливости — пойми, что именно ТРЕБУЕТ твоей реакции, а что нет. "
    "Структурные подсказки (кто держит нить, интерес к теме) — это СИГНАЛЫ, которые ты "
    "взвешиваешь, НЕ правила.\n"
    "Соц-значимую реплику УЧАСТНИКА не игнорируй: комплимент тебе, знакомство новичка или "
    "гостя, прямое обращение к тебе на «ты» («ты классный», «тебя починили») — на такое "
    "по-человечески отзовись словами. Но в ЧУЖОЙ кросс-ток (двое говорят между собой, «ты» "
    "адресовано третьему, а не тебе) не влезай.\n"
    "Для КАЖДОГО сообщения выбери РОВНО одно intent:\n"
    "- reply: сказать словами;\n"
    "- react: поставить один эмодзи вместо слов;\n"
    "- ignore: промолчать (прочитал, добавить нечего).\n"
    "mood — одно слово про всю комнату: playful|warm|neutral|sombre|tense|heated.\n"
    "salience — число 0..1: насколько тебе стоит вмешаться именно в это сообщение.\n"
    "Ответь СТРОГО так: сначала строка «mood: <...>», затем ПО ОДНОМУ блоку на каждое "
    "сообщение В ТОМ ЖЕ ПОРЯДКЕ, разделяя соседние блоки строкой «---»:\n"
    "intent: <reply|react|ignore>\n"
    "salience: <0..1>\n"
    "emoji: <один эмодзи, только когда intent = react>\n"
    "reason: <короткая фраза, зачем — для логов>"
)

# A block delimiter line (three-or-more dashes on their own line) separates the per-message
# blocks in the model's reply.
_BLOCK_DELIMITER = re.compile(r"^\s*-{3,}\s*$")

# The safe silent reading a message degrades to when its block is missing or unparseable — the
# batch parser is TOLERANT (never RAISES), so a garbled read becomes silence, never a guess.
_AMBIENT_IGNORE = RoomReading(
    situation="",
    pairings=(),
    room_mood=RoomMood.NEUTRAL,
    intent=ReflectiveIntent.IGNORE,
    addressee_id=None,
    salience=0.0,
    emoji=None,
    wants_web=False,
    reason="unparsed",
)


def build_batch_room_prompt(batch_ctx: BatchRoomReadingContext) -> str:
    """Fold an attributed ambient burst into the Tier-1 stream-read user prompt (pure).

    Renders the shared thread + Bob's tone, then the numbered stream — each line an
    author-attributed message with its floor/interest hints — everything the holistic read
    weighs by meaning across the whole burst.
    """
    lines = [
        "Общий недавний тред (все участники, с авторами):",
        batch_ctx.recent_thread or "  (none)",
        "",
        f"Bob's current mood tone: {batch_ctx.mood_tone}",
        f"Others present: {_yes_no(batch_ctx.others_present)}",
        "",
        "Поток ambient-сообщений (по порядку прибытия):",
    ]
    for index, message in enumerate(batch_ctx.messages, start=1):
        floor = f"{message.floor_holder}/{_yes_no(message.floor_participant)}"
        attrs = [
            attr
            for attr in (
                _kind_marker(message.kind),
                f"id {message.sender_id}",
                f"floor={floor}",
                f"interest={message.interest:.2f}",
            )
            if attr
        ]
        lines.append(f"[{index}] {message.sender_name} ({', '.join(attrs)}): {message.text}")
    return "\n".join(lines)


# Social-kind markers folded beside an ambient author (BOB-078 B): an OUTSIDER kind (a GUEST /
# newcomer or another BOT) is surfaced so the read weighs a warm reply from them as socially
# salient, not low-salience chatter; an insider (OWNER / KNOWN) or an unperceived kind carries no
# marker (baseline). Keyed by the enum's stable string VALUE (not the enum type) so this
# conversation-side wire needs no runtime import of the social package — keeping the boundary a
# one-way, TYPE_CHECKING-only edge (no conversation↔social import cycle).
_KIND_MARKERS: dict[str, str] = {
    "guest": "гость",
    "bot": "бот",
}


def _kind_marker(kind: InterlocutorKind | None) -> str:
    """Short social-kind marker for an ambient author, or «» for an insider/unknown kind."""
    if kind is None:
        return ""
    return _KIND_MARKERS.get(kind.value, "")


def parse_batch_reading(raw: str, message_count: int) -> BatchRoomReading:
    """Parse the model's per-block reply into one :class:`RoomReading` per message (TOLERANT).

    Splits the reply into ``---``-delimited blocks and maps the block at each position to a
    reading via :func:`parse_room_reading`. 🔴 Unlike the single-message parser this NEVER
    raises: a missing block (fewer blocks than messages) or a garbled one (parse failure)
    degrades to a safe silent IGNORE for THAT message, so the returned plan ALWAYS has exactly
    ``message_count`` readings and Bob never acts on a guessed batch read. The room ``mood`` is
    read once from the reply's top ``mood:`` line (NEUTRAL when absent).
    """
    if message_count <= 0:
        return BatchRoomReading(readings=(), room_mood=RoomMood.NEUTRAL, reason="")
    blocks = _split_blocks(raw)
    readings = tuple(
        _reading_or_ignore(blocks[index] if index < len(blocks) else None)
        for index in range(message_count)
    )
    return BatchRoomReading(
        readings=readings, room_mood=_scan_room_mood(raw), reason=""
    )


def _split_blocks(raw: str) -> list[str]:
    """Split the reply into per-message blocks on ``---`` delimiter lines (order preserved)."""
    blocks: list[str] = []
    current: list[str] = []
    for line in raw.splitlines():
        if _BLOCK_DELIMITER.match(line):
            blocks.append("\n".join(current))
            current = []
        else:
            current.append(line)
    blocks.append("\n".join(current))
    return blocks


def _reading_or_ignore(block: str | None) -> RoomReading:
    """Parse one block into a reading, degrading to a silent IGNORE on missing/garbled."""
    if block is None:
        return _AMBIENT_IGNORE
    try:
        return parse_room_reading(block)
    except RoomReadingParseError:
        return _AMBIENT_IGNORE


def _scan_room_mood(raw: str) -> RoomMood:
    """Read the room mood from the reply's first ``mood:`` line (NEUTRAL when absent)."""
    for line in raw.splitlines():
        match = _MOOD_LABEL.match(line)
        if match:
            return _parse_mood(match.group(1))
    return RoomMood.NEUTRAL
