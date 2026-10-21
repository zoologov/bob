# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""GuppiHandler — the GUPPI gatekeeper/admin identity (BOB-003 BEAD-03).

GUPPI is the second admin bot in the process: the gatekeeper in General and the
visible "you're not allowed" voice in Bob's topic. This module owns *only* GUPPI's
behaviours; the multi-bot router (:mod:`bob.infrastructure.telegram.multibot`)
dispatches its two BEAD-02 drop-hooks here:

* :meth:`GuppiHandler.reject` — an unauthorized user wrote in Bob's topic, so
  GUPPI sends the visible :data:`GUPPI_REJECT_TEXT` back into **that same chat +
  thread**. Bob's pipeline is never invoked. (The router only reaches this hook
  for the allowed group's Bob topic, so a stranger DM never triggers a reject.)
* :meth:`GuppiHandler.handle_general_command` — an owner-only command in General:
  ``/authorize <id>`` / ``/deauthorize <id>`` mutate the allowlist through the
  shared :class:`~bob.social.usecases.Authorizer` (no duplicated authz),
  ``/status`` answers a short whoami line (plus the LLM-provider health snapshot,
  :mod:`~bob.infrastructure.telegram.health_status`, when a ``HealthReader`` is wired —
  BOB-116), and — when a proactivity store is wired
  in — ``/quiet`` (optionally ``/quiet 2h`` for a timed mute) / ``/wake`` toggle
  Bob's per-persona proactivity flag (and its timed-mute expiry). A command from
  anyone but the owner, a non-command message, or any chat other than the General
  chat is **ignored and silent** — no reveal outside the group.

Transport only: GUPPI replies are sent through GUPPI's own injected bot (never
Bob's). The bot is behind the :class:`~bob.infrastructure.telegram.gateway.BotLike`
protocol so tests use a fake bot — no network.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol

from bob.infrastructure.telegram.health_status import render_health_status
from bob.proactivity.goals.state import GoalState, can_transition
from bob.proactivity.rule_announcement import (
    is_undelivered_proposal,
    unactionable_reason,
)
from bob.proactivity.self_improvement import (
    MAGNITUDE_RANGE_TOP,
    ProposalDefect,
    RuleState,
)
from bob.proactivity.self_improvement import (
    can_transition as rule_can_transition,
)

if TYPE_CHECKING:
    from datetime import datetime

    from bob.infrastructure.telegram.gateway import AuthorizerLike, BotLike
    from bob.kernel.ports import Clock, HealthReader
    from bob.proactivity.goals.graph import GoalGraph
    from bob.proactivity.self_improvement import ImprovementRule
    from bob.proactivity.state import ProactivityState
    from bob.proactivity.usecases.plan_goal import PlanGoal

__all__ = [
    "GUPPI_OUTAGE_TEXT",
    "GUPPI_REJECT_TEXT",
    "CodingAssistantLike",
    "GoalStoreLike",
    "GuppiHandler",
    "ProactivityStoreLike",
    "PursuitStoreLike",
    "RuleStoreLike",
]

# The single visible reject shown to an unauthorized user inside Bob's topic.
GUPPI_REJECT_TEXT = "⛔ Пользователь не авторизован"

# The honest outage notice GUPPI posts when an ESSENTIAL turn step fails after the
# bounded retries (BOB-049 .3 — «полный Боб или честный GUPPI-нотис»): Bob — the mind —
# is temporarily unavailable, so GUPPI (the infrastructure subsystem) reports it plainly
# instead of letting a degraded half-answer ship. Third-person system voice (it reads as
# GUPPI reporting, never Bob being rude). Russian (project language).
GUPPI_OUTAGE_TEXT = "⚠️ Проблемы со связью — Боб временно недоступен"

# The one-shot обида announcement GUPPI posts on a fresh sulk entry (BOB-014 .2b):
# the внеличностный systemic voice (NOT Bob himself) telling the owner Bob is hurt
# and not in the mood to talk right now. Posted once per entry (guarded upstream by
# the SulkState one-shot flag). Russian (project language).
GUPPI_SULK_ANNOUNCE_TEXT = "Боб обижен и сейчас не хочет разговаривать."

# Owner-only privileged commands GUPPI consumes in General.
_AUTHORIZE_COMMAND = "/authorize"
_DEAUTHORIZE_COMMAND = "/deauthorize"
_STATUS_COMMAND = "/status"
_QUIET_COMMAND = "/quiet"
_WAKE_COMMAND = "/wake"

# Owner-only goal-control commands GUPPI consumes in General (BOB-015 .2).
# `/goals` (+ the `stop`/`go` kill-switch sub-words) and `/goal <action> <id>`.
_GOALS_COMMAND = "/goals"
_GOAL_COMMAND = "/goal"
_GOALS_STOP_WORD = "stop"
_GOALS_GO_WORD = "go"
_GOAL_APPROVE = "approve"
_GOAL_PLAN = "plan"
_GOAL_PLAN_APPROVE = "plan-approve"
_GOAL_PAUSE = "pause"
_GOAL_RESUME = "resume"
_GOAL_CANCEL = "cancel"

# A goal action word -> the target GoalState its transition aims at. Each move is
# gated by ``can_transition`` so an illegal transition is rejected (not forced).
_GOAL_STATE_ACTIONS: dict[str, GoalState] = {
    _GOAL_APPROVE: GoalState.APPROVED,
    _GOAL_PAUSE: GoalState.PAUSED,
    _GOAL_RESUME: GoalState.ACTIVE,
    _GOAL_CANCEL: GoalState.CANCELLED,
}

# Owner-only coding-session command GUPPI consumes in General (BOB-039 .3):
# `/code <task>` starts a gated session, `/code approve|stop|status` drive it. Every
# `/code` is owner-only (the handle_general_command guard) and inert (a clear disabled
# reply) when the coding assistant is not wired (``coder.enabled`` false).
_CODE_COMMAND = "/code"
_CODE_APPROVE = "approve"
_CODE_STOP = "stop"
_CODE_STATUS = "status"
_CODE_DISABLED_TEXT = (
    "Запуск Claude Code выключен (coder.enabled=false) — включи его в конфиге."
)
_USAGE_CODE = "Использование: /code <задача> | /code approve | /code stop | /code status"

# Owner-only self-improvement-rule commands GUPPI consumes in General (BOB-028 .3).
# `/rules` lists Bob's rules; `/rule <action> <id>` is the owner approval gate —
# PROPOSED -> APPROVED happens ONLY here (authz-before-autonomy).
_RULES_COMMAND = "/rules"
_RULE_COMMAND = "/rule"
_RULE_APPROVE = "approve"
_RULE_REJECT = "reject"
_RULE_PAUSE = "pause"
_RULE_RESUME = "resume"
_RULE_REMOVE = "remove"

# A rule action word -> the target RuleState its transition aims at. Each move is
# gated by ``rule_can_transition`` so an illegal transition is rejected (not forced).
# Only these levers of CONTROL exist — owner approve/reject/pause/resume/remove; a rule
# can never grant a permission or a tool (it only ever tilts the Lever allowlist).
_RULE_STATE_ACTIONS: dict[str, RuleState] = {
    _RULE_APPROVE: RuleState.APPROVED,
    _RULE_REJECT: RuleState.REJECTED,
    _RULE_PAUSE: RuleState.PAUSED,
    _RULE_RESUME: RuleState.APPROVED,
    _RULE_REMOVE: RuleState.REMOVED,
}

_USAGE_RULE = "Использование: /rule <approve|reject|pause|resume|remove> <id> или /rules"
_RULES_EMPTY_TEXT = "Правил самоулучшения пока нет."
# Метка предложения, которое Боб пробовал проговорить и не смог (BOB-096 срез 1). После
# исчерпания попыток он о нём МОЛЧИТ — значит этот список остаётся единственным местом,
# где владелец о нём узнаёт; без метки предложение потерялось бы молча. Механика, а не
# речь Боба: её сообщает GUPPI своим списком.
_RULE_UNDELIVERED_MARK = " · не доставлено"
# Две метки предложения, о котором Боб молчит ПО СОДЕРЖАНИЮ (BOB-096, фикс ревью) — и
# они говорят РАЗНОЕ. «Нечего одобрять» — мусор: пустая поправка или нулевой наклон,
# никакая настройка его не спасёт. «Просит N при потолке M» — содержание есть, не хватает
# разрешения на величину, и владельцу тут есть что решать: поднять потолок или отклонить
# осознанно. 🔴 Одной меткой на оба случая мы назвали бы осмысленное предложение мусором
# (в живой базе таких три из четырёх) и отняли бы у владельца это решение. И ни та, ни
# другая — не «не доставлено»: доставка здесь ни при чём, иначе он ждал бы повторной
# попытки. Числа показываются намеренно: это ровно та информация, из которой он решает.
_RULE_UNACTIONABLE_MARK = " · нечего одобрять"
_RULE_ABOVE_CEILING_MARK = " · просит {magnitude:g} при потолке {ceiling:g}"
_RULE_REJECT_TEXT = "Не могу — для правила «{rule_id}» этот переход недопустим (сейчас {state})."
_RULE_NOT_FOUND_TEXT = "Правило «{rule_id}» не найдено."

_USAGE_GOAL = (
    "Использование: /goal <approve|plan|plan-approve|pause|resume|cancel> <id> "
    "или /goals [stop|go]"
)
_GOALS_EMPTY_TEXT = "Целей пока нет."
_GOALS_STOP_TEXT = "Остановил преследование целей — Боб больше не берётся за задачи сам."
_GOALS_GO_TEXT = "Снял стоп — Боб снова может браться за свои цели."
_PURSUIT_UNAVAILABLE = "Управление преследованием целей не подключено."
_GOAL_REJECT_TEXT = "Не могу — для цели «{goal_id}» этот переход недопустим (сейчас {state})."
_GOAL_NOT_FOUND_TEXT = "Цель «{goal_id}» не найдена."

_USAGE_AUTHORIZE = "Использование: /authorize <user_id>"
_USAGE_DEAUTHORIZE = "Использование: /deauthorize <user_id>"
_USAGE_QUIET = "Использование: /quiet [длительность], напр. /quiet 2h или /quiet 30m"
_STATUS_TEXT = "GUPPI на связи — привратник Боба. Команды: /authorize, /deauthorize, /status."
_QUIET_TEXT = "Боб притих — проактивность выключена."
_QUIET_TIMED_TEXT = "Боб притих до {until} — проактивность выключена."
_WAKE_TEXT = "Боб снова на связи — проактивность включена."

# Suffix → unit multiplier (to seconds) for the optional timed-mute duration.
_DURATION_UNITS = {"h": 3600, "m": 60, "s": 1}


class ProactivityStoreLike(Protocol):
    """The proactivity-store surface the owner /quiet, /wake commands need.

    A superset of the domain :class:`~bob.proactivity.ports.ProactivityStore` port: the
    owner commands also toggle the infrastructure-level timed-mute expiry, so the
    store must expose ``set_mute_until`` (the live :class:`SqliteProactivityStore`
    does). Kept structural so a fake satisfies it in tests.
    """

    async def load(self, persona_id: str) -> ProactivityState: ...
    async def save(self, persona_id: str, state: ProactivityState) -> None: ...
    async def set_mute_until(self, persona_id: str, until: datetime | None) -> None: ...


class GoalStoreLike(Protocol):
    """The goal-store surface GUPPI's goal commands need (load + state move).

    The read side (``load`` → a :class:`GoalGraph`) backs ``/goals`` and resolves a
    goal for an action; ``update_goal_state`` performs the owner state move
    (approve / pause / resume / cancel), each gated upstream by ``can_transition``.
    A structural subset of :class:`~bob.proactivity.ports.GoalStore` so a fake satisfies it.
    """

    async def load(self, persona_id: str) -> GoalGraph: ...
    async def update_goal_state(
        self, persona_id: str, goal_id: str, state: GoalState
    ) -> None: ...


class PursuitStoreLike(Protocol):
    """The kill-switch surface ``/goals stop`` / ``/goals go`` need (persist flag)."""

    async def set_pursuit_stopped(self, persona_id: str, *, stopped: bool) -> None: ...


class CodingAssistantLike(Protocol):
    """The CodingAssistant surface GUPPI's ``/code`` owner-commands need (BOB-039 .3).

    A structural subset of :class:`~bob.coding.usecases.coding_assistant.CodingAssistant`:
    ``start`` begins a gated session (plan-mode, the plan gate), ``approve_plan`` is the
    owner gate that lets execution proceed, ``stop`` is the kill-switch, ``status`` reports
    the in-flight state. The use-case enforces owner-only itself (defense-in-depth) and owns
    all owner messaging via its notifier, so GUPPI just routes the verb to it.
    """

    async def start(self, task: str, sender: int | None) -> object: ...
    async def approve_plan(self, sender: int | None) -> object: ...
    async def stop(self, sender: int | None) -> object: ...
    async def status(self, sender: int | None) -> object: ...


class RuleStoreLike(Protocol):
    """The self-improvement-rule-store surface GUPPI's rule commands need (BOB-028 .3).

    The read side (``load`` → the persisted rules) backs ``/rules`` and resolves a rule
    for an action; ``update_rule_state`` performs the owner state move (approve / reject
    / pause / resume / remove), each gated upstream by ``rule_can_transition``. ONLY the
    owner can call this path (the command guard), and the move never grants a permission
    or a tool — it merely flips the rule's :class:`RuleState`. A structural subset of
    :class:`~bob.proactivity.ports.SelfImprovementStore` so a fake satisfies it in tests.
    """

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]: ...
    async def update_rule_state(
        self, persona_id: str, rule_id: str, state: RuleState
    ) -> None: ...


class GuppiHandler:
    """GUPPI's gatekeeper behaviours: the visible reject + owner commands."""

    def __init__(
        self,
        *,
        bot: BotLike,
        authorizer: AuthorizerLike,
        general_chat_id: int,
        proactivity_store: ProactivityStoreLike | None = None,
        clock: Clock | None = None,
        persona_id: str = "bob",
        goal_store: GoalStoreLike | None = None,
        plan_goal: PlanGoal | None = None,
        pursuit_store: PursuitStoreLike | None = None,
        rule_store: RuleStoreLike | None = None,
        rule_max_magnitude: float = MAGNITUDE_RANGE_TOP,
        coding_assistant: CodingAssistantLike | None = None,
        coding_configured: bool = False,
        health: HealthReader | None = None,
    ) -> None:
        self._bot = bot
        self._authorizer = authorizer
        self._general_chat_id = general_chat_id
        self._proactivity_store = proactivity_store
        self._clock = clock
        self._persona_id = persona_id
        self._goal_store = goal_store
        self._plan_goal = plan_goal
        self._pursuit_store = pursuit_store
        self._rule_store = rule_store
        # The soft-tilt ceiling (``self_improvement.max_magnitude``) the ``/rules`` list
        # judges a proposal by — the SAME config value the announcer uses, so the list
        # and Bob's silence never disagree. The default is the whole unit range («no
        # configured ceiling was told»): then only an empty / zero-tilt proposal is
        # called unactionable, never an over-the-ceiling one.
        self._rule_max_magnitude = rule_max_magnitude
        # The gated coding assistant (BOB-039 .3). ``None`` when ``coder.enabled`` is
        # false (the conservative default); ``coding_configured`` says the feature
        # section exists at all, so an owner ``/code`` gets a clear "disabled" reply
        # instead of silently falling through.
        self._coding_assistant = coding_assistant
        self._coding_configured = coding_configured or coding_assistant is not None
        # Снимок здоровья LLM-провайдеров для ``/status`` (BOB-116 D6). ``None`` — монитор
        # не подключён: ``/status`` отвечает прежним текстом байт-в-байт.
        self._health = health

    async def reject(self, *, chat_id: int, thread_id: int | None) -> None:
        """Send the visible "unauthorized" reject into ``chat_id``/``thread_id``.

        The router only calls this for an unauthorized message inside the allowed
        group's Bob topic, so the reject is always scoped to the group (never a
        DM). Bob's pipeline is not invoked — GUPPI just speaks.
        """
        await self._bot.send_message(
            chat_id=chat_id,
            text=GUPPI_REJECT_TEXT,
            message_thread_id=thread_id,
        )

    async def announce_sulk(self) -> None:
        """Post the one-shot обида announcement into General (BOB-014 .2b).

        Realises :class:`~bob.social.usecases.sulk_sources.SulkAnnouncer`: on a
        fresh sulk entry GUPPI — the внеличностный systemic voice, never Bob himself —
        tells the owner Bob is hurt and not in the mood to talk. Posted into the General
        chat (where the owner sees GUPPI's system messages), exactly once per entry (the
        one-shot guard lives in the SulkState flag, so the application only calls this on
        the entry transition). Transport only — sent through GUPPI's own bot.
        """
        await self._reply(self._general_chat_id, GUPPI_SULK_ANNOUNCE_TEXT)

    async def handle_general_command(
        self, *, text: str, user_id: int | None, chat_id: int
    ) -> bool:
        """Handle an owner command in General; return whether it was consumed.

        Returns ``True`` only when GUPPI handled the message (a known owner command
        from the owner in the General chat). For a non-owner sender, a non-command
        message, or any chat other than General the call is silent and returns
        ``False`` — no reveal, no grant.
        """
        if chat_id != self._general_chat_id or not self._authorizer.is_owner(user_id):
            return False
        command, _, argument = text.strip().partition(" ")
        return (
            await self._dispatch_authz(chat_id, command, argument)
            or await self._dispatch_proactivity(chat_id, command, argument)
            or await self._dispatch_goals(chat_id, command, argument)
            or await self._dispatch_rules(chat_id, command, argument)
            or await self._dispatch_coding(chat_id, command, argument, user_id)
        )

    async def _dispatch_authz(self, chat_id: int, command: str, argument: str) -> bool:
        """Handle the allowlist owner commands; ``False`` if ``command`` is none of them."""
        if command == _AUTHORIZE_COMMAND:
            await self._grant(chat_id, argument, grant=True)
            return True
        if command == _DEAUTHORIZE_COMMAND:
            await self._grant(chat_id, argument, grant=False)
            return True
        if command == _STATUS_COMMAND:
            await self._reply(chat_id, self._status_text())
            return True
        return False

    def _status_text(self) -> str:
        """Ответ ``/status``: whoami-строка и, если подключён монитор, снимок здоровья LLM.

        Снимок читается в момент команды, а не при сборке: ``/status`` показывает то, что
        монитор знает сейчас.
        """
        if self._health is None:
            return _STATUS_TEXT
        return f"{_STATUS_TEXT}\n\n{render_health_status(self._health.snapshot())}"

    async def _dispatch_proactivity(self, chat_id: int, command: str, argument: str) -> bool:
        """Handle the /quiet, /wake owner commands when a proactivity store is wired."""
        if self._proactivity_store is None:
            return False
        if command == _QUIET_COMMAND:
            await self._quiet(chat_id, argument)
            return True
        if command == _WAKE_COMMAND:
            await self._wake(chat_id)
            return True
        return False

    async def _dispatch_goals(self, chat_id: int, command: str, argument: str) -> bool:
        """Handle the goal-control owner commands (BOB-015 .2); ``False`` if none match.

        ``/goals`` lists goals (``stop``/``go`` toggle the kill-switch); ``/goal
        <action> <id>`` runs a goal action. An unknown ``/goal`` action returns
        ``False`` (not consumed) so it never silently swallows a typo.
        """
        if self._goal_store is None:
            return False
        if command == _GOALS_COMMAND:
            await self._goals(chat_id, argument)
            return True
        if command == _GOAL_COMMAND:
            return await self._goal_action(chat_id, argument)
        return False

    async def _goals(self, chat_id: int, argument: str) -> None:
        """``/goals`` — list goals, or toggle the pursuit kill-switch (stop/go)."""
        word = argument.strip().lower()
        if word == _GOALS_STOP_WORD:
            await self._set_pursuit(chat_id, stopped=True, text=_GOALS_STOP_TEXT)
            return
        if word == _GOALS_GO_WORD:
            await self._set_pursuit(chat_id, stopped=False, text=_GOALS_GO_TEXT)
            return
        await self._reply(chat_id, await self._render_goals())

    async def _set_pursuit(self, chat_id: int, *, stopped: bool, text: str) -> None:
        """Persist the goal-pursuit kill-switch flag and confirm to the owner."""
        if self._pursuit_store is None:
            await self._reply(chat_id, _PURSUIT_UNAVAILABLE)
            return
        await self._pursuit_store.set_pursuit_stopped(self._persona_id, stopped=stopped)
        await self._reply(chat_id, text)

    async def _render_goals(self) -> str:
        """Render the owner-facing ``/goals`` list (goal title + state + task count)."""
        store = self._require_goal_store()
        graph = await store.load(self._persona_id)
        if not graph.goals:
            return _GOALS_EMPTY_TEXT
        lines = ["Цели Боба:"]
        for goal in graph.goals:
            count = len(graph.tasks_of(goal.id))
            lines.append(
                f"• [{goal.id}] {goal.title} — {goal.state.value} (задач: {count})"
            )
        return "\n".join(lines)

    async def _goal_action(self, chat_id: int, argument: str) -> bool:
        """Run a ``/goal <action> <id>`` command; ``False`` for an unknown action."""
        action, _, raw_id = argument.strip().partition(" ")
        goal_id = raw_id.strip()
        if not action or not goal_id:
            await self._reply(chat_id, _USAGE_GOAL)
            return True
        if action == _GOAL_PLAN:
            await self._goal_plan(chat_id, goal_id)
            return True
        if action == _GOAL_PLAN_APPROVE:
            await self._goal_plan_approve(chat_id, goal_id)
            return True
        if action in _GOAL_STATE_ACTIONS:
            await self._goal_state_move(chat_id, goal_id, _GOAL_STATE_ACTIONS[action])
            return True
        return False

    async def _goal_plan(self, chat_id: int, goal_id: str) -> None:
        """``/goal plan <id>`` — decompose the goal and show the plan (gate stays)."""
        if self._plan_goal is None:
            await self._reply(chat_id, _PURSUIT_UNAVAILABLE)
            return
        result = await self._plan_goal.run(goal_id)
        await self._reply(chat_id, result.message)

    async def _goal_plan_approve(self, chat_id: int, goal_id: str) -> None:
        """``/goal plan-approve <id>`` — the second gate (APPROVED → ACTIVE)."""
        if self._plan_goal is None:
            await self._reply(chat_id, _PURSUIT_UNAVAILABLE)
            return
        moved = await self._plan_goal.approve_plan(goal_id)
        if moved:
            await self._reply(chat_id, f"Цель «{goal_id}» активна — Боб может ей заняться.")
        else:
            await self._reply(chat_id, await self._reject_or_missing(goal_id))

    async def _goal_state_move(
        self, chat_id: int, goal_id: str, target: GoalState
    ) -> None:
        """Apply an owner state move (approve/pause/resume/cancel), gated by transition."""
        store = self._require_goal_store()
        graph = await store.load(self._persona_id)
        goal = graph.goal_by_id(goal_id)
        if goal is None:
            await self._reply(chat_id, _GOAL_NOT_FOUND_TEXT.format(goal_id=goal_id))
            return
        if not can_transition(goal.state, target):
            await self._reply(
                chat_id,
                _GOAL_REJECT_TEXT.format(goal_id=goal_id, state=goal.state.value),
            )
            return
        await store.update_goal_state(self._persona_id, goal_id, target)
        await self._reply(chat_id, f"Цель «{goal_id}» → {target.value}.")

    async def _reject_or_missing(self, goal_id: str) -> str:
        """Pick the right failure note for a plan-approve that didn't move the goal."""
        store = self._require_goal_store()
        graph = await store.load(self._persona_id)
        goal = graph.goal_by_id(goal_id)
        if goal is None:
            return _GOAL_NOT_FOUND_TEXT.format(goal_id=goal_id)
        return _GOAL_REJECT_TEXT.format(goal_id=goal_id, state=goal.state.value)

    def _require_goal_store(self) -> GoalStoreLike:
        """Return the wired goal store (the command guard ensures it exists)."""
        if self._goal_store is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("goal store not configured")
        return self._goal_store

    async def _dispatch_coding(
        self, chat_id: int, command: str, argument: str, user_id: int | None
    ) -> bool:
        """Handle the ``/code`` owner-command (BOB-039 .3); ``False`` if not ``/code``.

        ``/code <task>`` starts a gated session; ``/code approve|stop|status`` drive it.
        When the assistant is not wired (``coder.enabled`` false) the command is INERT —
        a clear "disabled" reply, never a silent drop. The use-case itself enforces
        owner-only and sends ALL owner messaging (plan / narration / PR / status) through
        its notifier, so GUPPI only routes the verb (with the verified owner id) and never
        re-sends.
        """
        if command != _CODE_COMMAND:
            return False
        if self._coding_assistant is None:
            if self._coding_configured:
                await self._reply(chat_id, _CODE_DISABLED_TEXT)
            else:
                return False
            return True
        await self._run_code(self._coding_assistant, argument, user_id)
        return True

    async def _run_code(
        self, assistant: CodingAssistantLike, argument: str, user_id: int | None
    ) -> None:
        """Route a ``/code`` sub-command to the gated coding assistant (owner verified)."""
        word = argument.strip()
        lowered = word.lower()
        if lowered == _CODE_APPROVE:
            await assistant.approve_plan(user_id)
        elif lowered == _CODE_STOP:
            await assistant.stop(user_id)
        elif lowered == _CODE_STATUS:
            await assistant.status(user_id)
        elif word:
            await assistant.start(word, user_id)
        else:
            await self._reply(self._general_chat_id, _USAGE_CODE)

    async def _dispatch_rules(self, chat_id: int, command: str, argument: str) -> bool:
        """Handle the self-improvement-rule owner commands (BOB-028 .3); ``False`` if none.

        ``/rules`` lists Bob's rules (id / state / lever); ``/rule <action> <id>`` runs
        an owner state move (approve / reject / pause / resume / remove). The approval
        gate lives ONLY here — PROPOSED -> APPROVED happens nowhere else (authz-before-
        autonomy). An unknown ``/rule`` action returns ``False`` (not consumed) so it
        never silently swallows a typo. No rule store wired → ``False`` (not consumed).
        """
        if self._rule_store is None:
            return False
        if command == _RULES_COMMAND:
            await self._reply(chat_id, await self._render_rules())
            return True
        if command == _RULE_COMMAND:
            return await self._rule_action(chat_id, argument)
        return False

    async def _render_rules(self) -> str:
        """Render the owner-facing ``/rules`` list (rule id + state + lever + observation).

        EVERY rule Bob has is listed — the list is the owner's full view, and Bob's
        silence about a rule must never look like the rule is gone. Two marks say WHY
        he is silent, and they say different things: «не доставлено» — the delivery
        attempts ran out (BOB-096 срез 1), «нечего одобрять» — the proposal is
        degenerate or over the configured ceiling, so there is nothing to answer
        (BOB-096, фикс ревью). Both verdicts are the domain's
        (:func:`is_undelivered_proposal` / :func:`is_unactionable_proposal`) — GUPPI
        only puts them into words.
        """
        store = self._require_rule_store()
        rules = await store.load(self._persona_id)
        if not rules:
            return _RULES_EMPTY_TEXT
        lines = ["Правила самоулучшения Боба:"]
        for rule in rules:
            lines.append(
                f"• [{rule.id}] {rule.state.value} · {rule.lever.value}"
                f"{self._rule_mark(rule)} — {rule.observation}"
            )
        return "\n".join(lines)

    def _rule_mark(self, rule: ImprovementRule) -> str:
        """Why Bob is silent about ``rule``, in the owner's words (or "" — he is not).

        The reason comes from the domain (:func:`unactionable_reason`); GUPPI only puts
        it into the owner's words, and an over-the-ceiling proposal gets BOTH numbers —
        what it asks for and what is allowed — because that is exactly what he decides
        from. Content beats delivery bookkeeping by construction (the domain ranks it
        that way), so a rule silenced by its content is never also called «не
        доставлено». The ceiling is the one this GUPPI was wired with — the same config
        value the announcer judges by, so the list and Bob's silence never disagree.
        """
        reason = unactionable_reason(rule, max_magnitude=self._rule_max_magnitude)
        if reason is ProposalDefect.NOTHING_TO_APPROVE:
            return _RULE_UNACTIONABLE_MARK
        if reason is ProposalDefect.ABOVE_CEILING:
            return _RULE_ABOVE_CEILING_MARK.format(
                magnitude=rule.magnitude, ceiling=self._rule_max_magnitude
            )
        if is_undelivered_proposal(rule, max_magnitude=self._rule_max_magnitude):
            return _RULE_UNDELIVERED_MARK
        return ""

    async def _rule_action(self, chat_id: int, argument: str) -> bool:
        """Run a ``/rule <action> <id>`` command; ``False`` for an unknown action."""
        action, _, raw_id = argument.strip().partition(" ")
        rule_id = raw_id.strip()
        if not action or not rule_id:
            await self._reply(chat_id, _USAGE_RULE)
            return True
        if action in _RULE_STATE_ACTIONS:
            await self._rule_state_move(chat_id, rule_id, _RULE_STATE_ACTIONS[action])
            return True
        return False

    async def _rule_state_move(
        self, chat_id: int, rule_id: str, target: RuleState
    ) -> None:
        """Apply an owner rule state move, gated by the rule transition machine.

        Loads the rule, checks ``rule_can_transition`` (an illegal move — e.g. approving
        an already-REMOVED rule — is rejected, not forced), then persists the new state
        via ``update_rule_state``. This is the SOLE path PROPOSED -> APPROVED, so no rule
        ever influences behaviour without the owner's explicit approve here.
        """
        store = self._require_rule_store()
        rules = await store.load(self._persona_id)
        rule = next((r for r in rules if r.id == rule_id), None)
        if rule is None:
            await self._reply(chat_id, _RULE_NOT_FOUND_TEXT.format(rule_id=rule_id))
            return
        if not rule_can_transition(rule.state, target):
            await self._reply(
                chat_id,
                _RULE_REJECT_TEXT.format(rule_id=rule_id, state=rule.state.value),
            )
            return
        await store.update_rule_state(self._persona_id, rule_id, target)
        await self._reply(chat_id, f"Правило «{rule_id}» → {target.value}.")

    def _require_rule_store(self) -> RuleStoreLike:
        """Return the wired rule store (the command guard ensures it exists)."""
        if self._rule_store is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("rule store not configured")
        return self._rule_store

    async def _quiet(self, chat_id: int, argument: str) -> None:
        """Mute proactivity; an optional duration (``2h``/``30m``) adds an expiry."""
        store = self._require_store()
        until = self._parse_until(argument)
        if argument.strip() and until is None:
            await self._reply(chat_id, _USAGE_QUIET)
            return
        await self._set_enabled(store, enabled=False)
        await store.set_mute_until(self._persona_id, until)
        if until is None:
            await self._reply(chat_id, _QUIET_TEXT)
        else:
            await self._reply(chat_id, _QUIET_TIMED_TEXT.format(until=until.isoformat()))

    async def _wake(self, chat_id: int) -> None:
        """Un-mute proactivity and clear any timed-mute expiry."""
        store = self._require_store()
        await self._set_enabled(store, enabled=True)
        await store.set_mute_until(self._persona_id, None)
        await self._reply(chat_id, _WAKE_TEXT)

    async def _set_enabled(self, store: ProactivityStoreLike, *, enabled: bool) -> None:
        """Toggle the persisted ``proactivity_enabled`` flag (state-preserving)."""
        state = await store.load(self._persona_id)
        await store.save(self._persona_id, replace(state, proactivity_enabled=enabled))

    def _require_store(self) -> ProactivityStoreLike:
        """Return the wired proactivity store (the command guard ensures it exists)."""
        if self._proactivity_store is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("proactivity store not configured")
        return self._proactivity_store

    def _parse_until(self, argument: str) -> datetime | None:
        """Resolve an optional duration argument into an absolute expiry instant.

        Returns ``None`` for an empty argument (an indefinite mute) or an
        unparseable one; the caller distinguishes the two by re-checking the text.
        """
        seconds = _parse_duration_seconds(argument)
        if seconds is None or self._clock is None:
            return None
        return self._clock.now() + timedelta(seconds=seconds)

    async def _grant(self, chat_id: int, argument: str, *, grant: bool) -> None:
        """Apply an authorize/deauthorize grant and confirm to the owner."""
        target = _parse_user_id(argument)
        if target is None:
            await self._reply(
                chat_id, _USAGE_AUTHORIZE if grant else _USAGE_DEAUTHORIZE
            )
            return
        if grant:
            await self._authorizer.authorize(target)
            await self._reply(chat_id, f"Пользователь {target} авторизован.")
        else:
            await self._authorizer.deauthorize(target)
            await self._reply(chat_id, f"Пользователь {target} деавторизован.")

    async def _reply(self, chat_id: int, text: str) -> None:
        """Send a GUPPI reply into General (un-threaded)."""
        await self._bot.send_message(chat_id=chat_id, text=text, message_thread_id=None)


def _parse_user_id(argument: str) -> int | None:
    """Parse the ``<user_id>`` argument of an owner command; ``None`` if invalid."""
    cleaned = argument.strip()
    if not cleaned.lstrip("-").isdigit():
        return None
    return int(cleaned)


def _parse_duration_seconds(argument: str) -> int | None:
    """Parse a ``/quiet`` duration (``2h`` / ``30m`` / ``45s``) into seconds.

    Returns ``None`` for an empty argument (no timed mute) or any value that is
    not a positive integer followed by a known unit suffix.
    """
    cleaned = argument.strip().lower()
    if not cleaned:
        return None
    unit = cleaned[-1]
    multiplier = _DURATION_UNITS.get(unit)
    amount = cleaned[:-1]
    if multiplier is None or not amount.isdigit():
        return None
    value = int(amount)
    return None if value <= 0 else value * multiplier
