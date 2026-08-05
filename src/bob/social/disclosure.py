# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=domain

"""Disclosure tact — the initiative-surfacing filter of scope provenance (BOB-066 2.6).

Такт разглашения is a distinct concern from the privilege gate (BOB-052): the gate
decides what a person may *ask* Bob to do or reveal; this decides what Bob *initiatively
surfaces* from his own memory into a reply. The two are orthogonal — a guest can hold a
perfectly ordinary conversation (memory is public, BOB-051) yet Bob must not volunteer
the owner's private things to them.

* :func:`may_surface` — the pure predicate the recall pipeline consults per memory: an
  ``owner_private`` item never surfaces initiatively to a GUEST, while a ``public`` (or a
  legacy ``NULL``) item always does. A TRUSTED interlocutor (the
  owner or a known peer) sees EVERYTHING, so owner-facing recall is byte-identical (INV-7)
  — the filter is latent until a guest is actually live.
* :func:`visibility_for_scope` — the conservative write-side classifier: a group turn is
  ``public`` (shared group memory), an owner-DM or an *uncertain* scope is ``owner_private``
  (fail-safe, INV-8 — doubt withholds rather than leaks).

Pure and deterministic (no I/O, same inputs → same verdict), so both the write path and
the recall filter stay testable without a store or an LLM. ``NULL`` = public keeps
BOB-051 unified memory and every legacy row intact.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.social.interlocutor import Trust

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "VISIBILITY_OWNER_PRIVATE",
    "VISIBILITY_PUBLIC",
    "carries_owner_private",
    "filter_surfaceable",
    "may_surface",
    "transfer_needs_consent",
    "visibility_for_scope",
]

# The two provenance tags a memory may carry. Persisted as a nullable column whose
# ``NULL`` default reads as PUBLIC — so BOB-051 unified memory and every pre-migration
# row stay surfaceable to anyone, and only a turn Bob deliberately tags private is held.
VISIBILITY_PUBLIC = "public"
VISIBILITY_OWNER_PRIVATE = "owner_private"


def may_surface(
    visibility: str | None, trust: Trust, *, owner_consented: bool = False
) -> bool:
    """Whether a memory of this ``visibility`` may surface INITIATIVELY to ``trust`` — pure.

    A TRUSTED interlocutor (the owner or a known peer) always sees the memory, so
    owner-facing recall is unchanged byte-for-byte (INV-7). For a GUEST, only an
    ``owner_private`` item is withheld; ``public`` — and, defensively, a legacy ``NULL``
    or any UNRECOGNISED value — surfaces (``NULL`` = public keeps BOB-051 memory intact,
    and an unknown tag is never allowed to silently hide public memory). The
    ``owner_private`` match is case-insensitive.

    ``owner_consented`` (BOB-082 .4) is the per-turn OWNER-consent override: when the owner
    has, in THIS turn, authorised Bob to voice previously-private content into the room, an
    ``owner_private`` item is permitted to pass even to a GUEST-guarded (group) audience —
    a one-time disclosure, never a reclassification of the stored memory. It only ever
    WIDENS (public and TRUSTED are unaffected); its default ``False`` keeps every existing
    call byte-identical. Deterministic: same inputs → same verdict.
    """
    if trust is Trust.TRUSTED or owner_consented:
        return True
    normalised = (visibility or "").strip().casefold()
    return normalised != VISIBILITY_OWNER_PRIVATE


def visibility_for_scope(*, is_group: bool | None) -> str:
    """Classify the visibility a turn's memory should be written with (pure, BOB-066 2.6).

    A confidently GROUP turn (``is_group=True``) is ``public`` shared memory — everyone
    in the room is party to it. An owner-DM turn (``False``) or an UNCERTAIN scope
    (``None``) is ``owner_private``: the conservative, fail-safe default (INV-8) so that
    doubt withholds rather than leaks the owner's private world. Deterministic.
    """
    return VISIBILITY_PUBLIC if is_group is True else VISIBILITY_OWNER_PRIVATE


def filter_surfaceable(
    recalled: Sequence[Mapping[str, object]],
    trust: Trust,
    *,
    owner_consented: bool = False,
) -> tuple[Mapping[str, object], ...]:
    """Drop owner-private recalled memories that may not surface to ``trust`` — pure.

    The recall-pipeline filter of такт разглашения (mirrors
    :func:`~bob.conversation.conversation.recalled_excluding_reflections`): keeps every
    memory :func:`may_surface` allows for this interlocutor's ``trust``, reading each
    item's ``visibility`` field. For a TRUSTED interlocutor every item passes, so the
    result is byte-identical to the input (INV-7 — owner recall unchanged); for a GUEST
    only ``owner_private`` items are withheld.

    ``owner_consented`` (BOB-082 .4) threads the per-turn OWNER-consent override into the
    filter: when ``True`` the withheld ``owner_private`` items are also let through for
    THIS turn (a one-time disclosure the owner authorised). Default ``False`` = the
    behaviour as before, byte-identical. Deterministic and order-preserving.
    """
    return tuple(
        item
        for item in recalled
        if may_surface(_visibility_of(item), trust, owner_consented=owner_consented)
    )


def carries_owner_private(material: Sequence[Mapping[str, object]]) -> bool:
    """Whether ``material`` holds anything owner-private — pure (BOB-090.B4).

    The read side of такт разглашения over a whole BODY of material: an item counts as
    private exactly when :func:`may_surface` would withhold it from a GUEST, so there is
    ONE definition of «приватное» in the codebase and not a second, drifting one. A legacy
    ``NULL`` (or an unrecognised tag) reads as public, exactly as everywhere else.
    """
    return any(
        not may_surface(_visibility_of(item), Trust.GUEST) for item in material
    )


def transfer_needs_consent(
    recalled: Sequence[Mapping[str, object]], *, destination_public: bool
) -> bool:
    """Whether carrying material Bob ADDS to a public destination needs consent — pure.

    🔴 Решение owner'а (BOB-090.B4): перенос считается **ПО МАТЕРИАЛУ, а не по форме**.
    A message whose material includes an ``owner_private`` item is a transfer whether it
    quotes or retells in Bob's own words — otherwise «расскажи Норману, о чём мы говорили»
    would walk around the gate by simple rewording. The gate reads the LABEL of the
    material, never the wording, so the two forms are indistinguishable to it.

    🔴 Материал — это то, что Боб ДОБАВЛЯЕТ ОТ СЕБЯ: приватные эпизоды, поднятые памятью
    (``recalled``). Место, где идёт разговор, триггером НЕ является (BOB-090.B-fix): пока
    им считалась личка — приватная целиком, — гейт срабатывал на КАЖДОЙ отправке из лички
    независимо от материала, и Боб отказывал owner'у в его же прямом распоряжении
    («напиши в группу, что я закончил обзор»). Просьба owner'а — это волеизъявление, а не
    утечка: согласие содержится в самой команде. Спрашивать надо там, где содержание
    приходит из ПАМЯТИ Боба, а не изо рта owner'а.

    🔴 ОСОЗНАННЫЙ ОСТАТОЧНЫЙ РИСК (решение owner'а, чинить не надо): если owner прямо
    велит переслать в комнату сказанное им же в личке, а память ничего приватного не
    подняла, отправка уйдёт без вопроса. Это его данные и его решение — Боб исполняет.
    Гейт остаётся ровно там, где Боб выносит приватное ПО СВОЕЙ инициативе.

    Consent is only ever a question when the AUDIENCE changes: a ``destination_public``
    of ``False`` (writing back to the owner himself) is never a transfer. Deterministic.
    """
    return destination_public and carries_owner_private(recalled)


def _visibility_of(item: Mapping[str, object]) -> str | None:
    """Read a recalled memory's ``visibility`` tag as a string, or ``None`` (= public)."""
    value = item.get("visibility")
    return value if isinstance(value, str) else None
