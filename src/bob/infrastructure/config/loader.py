# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""ConfigLoader — layered configuration: defaults -> YAML file -> environment.

Precedence (lowest to highest): built-in :data:`DEFAULT_CONFIG`, an optional YAML
file (``yaml.safe_load``), then environment variables. Env vars use the prefix
``BOB_`` and ``__`` to denote nesting, e.g. ``BOB_LLM__TIER1_MODEL`` maps to
``config["llm"]["tier1_model"]``. Later layers deep-merge over earlier ones.
An env value takes the type of the built-in default at its path (``int``, ``float``,
``bool``, a comma-separated list) — see :mod:`bob.infrastructure.config.env_coercion`;
a path with no default keeps the raw string.

Two-bot tokens are special-cased because they don't follow the nesting rule
one-to-one: the bot tokens live under ``telegram.bob.token`` /
``telegram.guppi.token`` but are fed by the flat env vars ``BOB_TELEGRAM__TOKEN``
(the historical name) and ``GUPPI_TELEGRAM__TOKEN`` (a non-standard prefix the
generic ``BOB_`` mechanism cannot pick up). :data:`_TOKEN_ENV_MAPPING` maps each
env var to its explicit nested path; these are applied last so env still wins.
"""

from __future__ import annotations

import copy
import logging
import os
from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, Any

import yaml

from bob.infrastructure.config.env_coercion import ElementType, coerce_env_value

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# A nested configuration tree (string keys; values are scalars or sub-mappings).
type Config = dict[str, Any]

_ENV_PREFIX = "BOB_"
_ENV_NESTING_SEPARATOR = "__"

# Explicit env-var -> nested config path mapping for the two bot tokens. The
# generic BOB_ nesting cannot express either: BOB_TELEGRAM__TOKEN would land at
# telegram.token (not telegram.bob.token), and GUPPI_TELEGRAM__TOKEN does not
# carry the BOB_ prefix at all. Applied after the generic env layer so env wins.
_TOKEN_ENV_MAPPING: dict[str, tuple[str, ...]] = {
    "BOB_TELEGRAM__TOKEN": ("telegram", "bob", "token"),
    "GUPPI_TELEGRAM__TOKEN": ("telegram", "guppi", "token"),
}

# Element type of a list whose built-in default is EMPTY and so cannot say what it holds.
# A list default with elements types its env items by them; an empty one not named here
# takes strings (``coder.extra_dirs``, ``goals.safe_capabilities``). The chat allowlist
# is fed from ``.env`` on the VPS (the tracked config carries no ids, BOB-116), so its
# items must arrive as ints — the consumer drops anything that is not one.
_LIST_ELEMENT_TYPES: dict[tuple[str, ...], ElementType] = {
    ("telegram", "allowed_chat_ids"): int,
}

# Built-in defaults — the safe baseline the runtime boots from with no YAML/env.
DEFAULT_CONFIG: Config = {
    "runtime": {
        "log_level": "INFO",
        "heartbeat_seconds": 30,
        # The persona's language for self-generated text (proactive compose, the
        # Tier-0 gate, the inner-monologue / reflection ticks) — these have no user
        # message to mirror, so without this constraint the model drifts to English
        # (BOB-012). Default Russian; a Bobiverse replica can override by config.
        "language": "ru",
    },
    "llm": {
        "tier0_model": "qwen2.5:0.5b",
        "tier1_model": "qwen2.5:7b",
        # Generous timeout for slow Tier 1 reasoning replies (seconds). A float: the
        # factory reads it as one, and an env value is coerced to the default's type.
        "timeout_seconds": 180.0,
        # Replies don't need chain-of-thought: disabling it cuts cost/latency and
        # avoids the empty-content case where a reasoning model spends its whole
        # budget on reasoning_content.
        "disable_thinking": True,
        # Sampling temperature per tier (BOB-022): without it Qwen MaaS decodes
        # greedily, so an identical prompt returns byte-identical text (the
        # verbatim-repeat bug). Tier 0 (classification/sentiment/summary) runs
        # steadier; Tier 1 (user-facing replies/monologue) runs more varied for
        # natural variation. The factory threads these into each provider.
        "tier0_temperature": 0.5,
        "tier1_temperature": 0.8,
        # 🔴 EMERGENCY mode, not a second main model (BOB-087.E1, BOB-Issues #34).
        # A CLOUD Tier 0 (Qwen/Aliyun) periodically drops off the network — BOB-084
        # saw 77 outages in a row — and an outage takes the classifiers, the inner
        # monologue and the coding gates with it. Naming a local backend here
        # (``ollama`` — the only one supported) lets a Tier-0 TRANSPORT failure
        # degrade to the local model below instead of failing the turn; contract
        # failures (4xx, a broken response shape) still surface, so the fallback can
        # never mask our own bugs. Empty (the default) = OFF: Tier 0 is built exactly
        # as before. The ``/v1`` suffix is Ollama's OpenAI-compatible chat surface
        # (the ``embeddings``/``reranker`` sections point at the bare host because
        # their adapters append their own paths).
        "tier0_fallback": "",
        "tier0_fallback_base_url": "http://localhost:11434/v1",
        "tier0_fallback_model": "qwen2.5:0.5b",
        # Provider health (BOB-116): a provider that keeps failing is declared DEGRADED
        # after ``failures_threshold`` consecutive failures OR ``duration_threshold_seconds``
        # of failing, whichever comes first; the owner gets one signal then reminders on
        # the ``reminders_seconds`` schedule (the last interval repeats), and a degraded
        # provider is probed on the ``probe_seconds`` schedule (the last one repeats).
        # ``owner_alert`` false keeps the log line and drops the owner's message.
        "health": {
            "failures_threshold": 5,
            "duration_threshold_seconds": 180,
            "reminders_seconds": [600, 3600, 21600, 86400],
            "probe_seconds": [60, 120, 300],
            "owner_alert": True,
        },
    },
    # Local semantic-memory embeddings (BOB-011). Provider-agnostic: a LOCAL
    # Ollama server (privacy — memory content never leaves the machine), default
    # model BGE-M3 (dense, 1024-dim, multilingual/Russian). Swap ``model``/``dim``
    # (e.g. Qwen3-Embedding) without touching consumers.
    "embeddings": {
        "base_url": "http://localhost:11434",
        "model": "bge-m3",
        "dim": 1024,
    },
    # Local reranker (BOB-011 BEAD-04) — an ADDITIVE quality boost on top of the
    # hybrid recall: re-scores the top-K pool and trims to top_n. Off by default
    # (``enabled`` false): wiring it in is BEAD-06's job. Ollama exposes no native
    # rerank endpoint (Q1), so the adapter scores via a LOCAL model over the
    # OpenAI-compatible chat API — memory content never leaves the machine. Swap
    # ``model`` (e.g. a Qwen3-Reranker / bge-reranker-v2-m3 GGUF) via config.
    "reranker": {
        "enabled": False,
        "base_url": "http://localhost:11434",
        "model": "bge-reranker-v2-m3",
        # top-K candidates from RRF in, top-N reranked out (Q4: ~20-50 -> ~5-8).
        "top_n": 8,
    },
    # Spontaneous expression (BOB-018): per turn a pure ExpressionPlan picks how
    # Bob expresses himself (full reply vs. a terse react-only ack + rare add-on
    # flags + a soft form hint), deterministically from mood + a seeded RNG. The
    # add-on flags fire on a small, configurable fraction of turns (anti-tic):
    # ``leak_inner_life`` surfaces a real recent reflection, ``callback`` a real
    # past moment. Defaults are deliberately small; tune per persona. The seed
    # reuses the proactivity seed (``runtime.proactivity_seed``) so one knob makes
    # all of Bob's stochastic behaviour reproducible in tests.
    "expression": {
        "freqs": {
            "leak_inner_life": 0.12,
            "callback": 0.1,
            # How often Bob surfaces his CURRENT fascination à propos (BOB-020). Small
            # (anti-tic); no fascination → the compose no-ops regardless.
            "mention_fascination": 0.1,
        },
    },
    # Emotional depth (BOB-020). ``offday`` is the mood floor below which Bob's tone
    # goes quieter/vulnerable/honest. ``fascination`` tunes his evolving current
    # passion: ``initial_intensity`` is how vivid a freshly-picked fascination starts
    # (it then decays with age); ``mention_freq`` mirrors the expression flag above so
    # surfacing stays a single configurable knob.
    "emotion": {
        "fascination": {
            "initial_intensity": 0.85,
            "mention_freq": 0.1,
        },
    },
    # Conversational appetite (BOB-014 .2a): Bob's appetite to converse is a LEVEL
    # (full / playful / terse / decline) decided per turn from mood x topic interest x
    # conversational fatigue x relationship. ``thresholds`` tune the appetite boundaries
    # (``interesting`` interest bar, ``high_fatigue`` "наскучило" point, ``low_mood`` /
    # ``bright_mood`` mood bands, ``playful_chance`` banter probability); ``fatigue`` tunes
    # the bounded reservoir's dynamics (``decay_per_second`` — the recovery guarantee,
    # ``aimless_rise``, ``interest_ease``); ``mood_lift`` is the small valence bump a good,
    # interesting exchange earns. Defaults keep a normal mood fully engaging on any
    # non-trivial topic and guarantee fatigue always recovers (no permanent lock-out).
    "engagement": {
        "thresholds": {
            "interesting": 0.5,
            "high_fatigue": 0.7,
            "low_mood": -0.3,
            "bright_mood": 0.3,
            "playful_chance": 0.6,
        },
        "fatigue": {
            "decay_per_second": 1.0 / 3600.0,
            "aimless_rise": 0.15,
            "interest_ease": 0.25,
        },
        "mood_lift": 0.1,
    },
    # Addressivity policy (BOB-023): Bob perceives WHO a message is for — him, another
    # participant, or no one — and decides engage / quietly like-react / stay SILENT, so
    # he no longer barges into every group exchange. Conservative defaults: he almost
    # never cuts into someone else's exchange. ``barge_in_interest`` is the HIGH interest
    # bar to RARELY join a message aimed at another (at ``barge_in_freq`` frequency);
    # ``ambient_interest`` is the lower bar to join a general ambient turn with others
    # around (at ``ambient_barge_in_freq``, easier); ``react_chance`` is how often an
    # ambient-with-others turn becomes a quiet like-reaction instead of full silence.
    "addressivity": {
        "barge_in_interest": 0.8,
        "ambient_interest": 0.6,
        "barge_in_freq": 0.05,
        "ambient_barge_in_freq": 0.15,
        "react_chance": 0.3,
        # Conversational floor (BOB-025): over the per-message addressivity lives a
        # tracker of who currently holds the "talking turn" in a thread. While Bob holds
        # a live floor, an ambient message from ANY participant reads as DIRECTED_TO_BOB
        # (continuity — owner and guest talk to Bob without re-tagging each message); the
        # floor sticks on a direct address / Bob's reply and decays by timeout or after a
        # silent-ambient streak. ``enabled`` true wires it; ``timeout_seconds`` (~5 min)
        # is the floor's life without re-confirmation; ``reset_after_silent`` is how many
        # silent ambient turns collapse Bob's floor to idle. Disabled → exactly BOB-023.
        "floor": {
            "enabled": True,
            "timeout_seconds": 300,
            "reset_after_silent": 2,
        },
    },
    # Brevity — краткость по запросу (BOB-024): Bob's reply LENGTH stops being a constant.
    # The answer-demand of the message x topic interest x mood/appetite x the BOB-018
    # form_hint decide a verbosity (terse / normal / expansive), which becomes the single
    # final length directive + (on a terse turn) the short-answer few-shot that beats
    # Qwen's verbosity prior. ``thresholds`` tune the verbosity decision: ``interest_upgrade``
    # (the high interest bar that can rarely upgrade a turn) at ``upgrade_freq`` (the small
    # seeded chance), ``bad_mood`` / ``low_engagement`` (the mood/appetite points that pull a
    # step down), ``tilt_mood`` (the soft-mood point where a terse form_hint adds a downshift).
    # ``length_guard`` is the OPTIONAL safety net behind the bayes: ``enabled`` false by
    # default — only when on AND the demand is LOW is an over-long reply lightly clamped to
    # its first finished thought (``max_chars``), never a regeneration. Defaults are
    # conservative; the bayes (directive + few-shot) is the mechanism, the guard a backstop.
    "brevity": {
        "thresholds": {
            "interest_upgrade": 0.85,
            "upgrade_freq": 0.1,
            "bad_mood": -0.5,
            "low_engagement": 0.25,
            "tilt_mood": -0.25,
        },
        "length_guard": {
            "enabled": False,
            "max_chars": 280,
        },
    },
    # Dialogue coherence (BOB-044). ``recent_turns`` is how many recent conversation
    # turns are replayed into the reply context so Bob holds the thread. The old
    # hardcoded window of 6 was too tight — an earlier topic fell out before Bob could
    # come back to it, so he "lost the thread". Widened to 14; raise it further for a
    # persona that needs to hold longer arcs. Must be a positive int. This is the
    # conversation-replay window only — independent of the anti-repeat ``repeat.*``
    # windows (BOB-026/036) and the wide tic-guard ``repeat.tic_lookback`` (BOB-043).
    "dialogue": {
        "recent_turns": 14,
        # Long-gap absence texture (BOB-045 .3). When Bob resumes with a person after a
        # pause longer than this many hours, a LIGHT contextual hint ("последний разговор
        # был ...") is folded into the compose context so he notices the gap humanly — a
        # hint for the reply tier, never a scripted phrase. Per-person (owner and guest
        # alike). ``0`` disables it; must be non-negative.
        "absence_hint_hours": 8.0,
    },
    # Memory consolidation (BOB-021): a rare, non-destructive reflect-tick step that
    # folds OLD un-consolidated episodes into a Tier-0 digest (embedded, recalled like
    # any episode) and flags the sources. Conservative defaults: only episodes at least
    # two weeks old are eligible, a modest batch per tick. ``enabled`` false keeps the
    # step inert until deliberately switched on per persona.
    "memory": {
        "consolidation": {
            "enabled": False,
            "max_age_days": 14.0,
            "batch_size": 50,
        },
        # Fact dedup (BOB-021): a rare, conservative, non-destructive reflect-tick step
        # that merges near-duplicate semantic facts (cosine of embeddings above a high
        # threshold) into a canonical one, flagging the rest superseded (excluded from
        # recall, never deleted). ``threshold`` is deliberately high so dissimilar facts
        # are never merged; ``enabled`` false keeps the step inert until switched on. It
        # needs an embedder — with keyword-only memory the step is a no-op.
        "dedup": {
            "enabled": False,
            "threshold": 0.92,
            "batch_size": 200,
        },
        # Surface-old (BOB-021 mechanism 1, "что-то напомнило"): on a (rare) BOB-018
        # callback turn, Bob occasionally reaches for an OLD-but-relevant memory via
        # recall's additive ``surface_old`` opt-in, so a deep cut can come back à propos.
        # ``freq`` is how often a callback asks for the old blend — small (anti-tic), and
        # it rides ONLY the callback path. The default recall is unchanged (drop-in); a
        # callback with no old-but-relevant hit is a clean no-op (Bob never confabulates).
        "surface_old": {
            "freq": 0.15,
        },
    },
    # Autonomy — Goal Engine (BOB-015). ``require_plan_approval`` is the DOUBLE-gate
    # default (true): after the owner approves a goal, the Planner decomposes it and
    # the plan must ALSO be approved before the goal goes ACTIVE — conservative at the
    # start of autonomy (set false for a single-gate flow). ``planner_tier`` pins the
    # decomposition tier (1 = reasoning model). The remaining keys are PLACEHOLDERS the
    # self-directed tick (.3) will read: ``tick_seconds`` (pursuit cadence),
    # ``max_tasks_per_window`` (a rate-limit on top of governance), ``pursuit_stopped``
    # (kill-switch default — false = Bob may pursue, but a goal must still be APPROVED),
    # and ``safe_capabilities`` (the allowlist the autonomous path may execute; an empty
    # default means the tick runs no capability until one is deliberately allowed).
    "goals": {
        "require_plan_approval": True,
        "planner_tier": 1,
        # ``pursuit_enabled`` (BOB-015 .3) is the master switch for the self-directed
        # tick — OFF by default (conservative start of autonomy-execution): the tick
        # is scheduled ONLY when the owner switches it on. ``tick_seconds`` is its
        # (rare) cadence; ``max_tasks_per_window`` rate-limits advances on top of the
        # governance ceiling; ``safe_capabilities`` is the allowlist the autonomous
        # path may run (an empty default → it runs no capability); ``pursuit_stopped``
        # is the kill-switch default (false = Bob may pursue, but a goal must still be
        # APPROVED).
        "pursuit_enabled": False,
        "tick_seconds": 900,
        "max_tasks_per_window": 1,
        "pursuit_stopped": False,
        "safe_capabilities": [],
    },
    # Self-improvement — metacognitive learning on patterns (BOB-028). PLACEHOLDERS
    # the detector (.2) + apply flow (.3) read. ``enabled`` is the MASTER SWITCH —
    # OFF by default (conservative start of metacognition): the detector is scheduled
    # and rules are applied ONLY when the owner switches it on; OFF → behaviour is
    # exactly as before BOB-028. ``detect_cadence`` is how rarely the reflect-tick
    # seam runs the detector (every Nth slow tick); ``detector_tier`` pins the LLM
    # tier the detector reasons on (1 = reasoning model). ``max_active_rules`` caps
    # how many LIVE rules (PROPOSED/APPROVED/PAUSED) may accrue so the detector never
    # floods the owner. ``max_magnitude`` (the soft-tilt ceiling) is read by the
    # apply flow (.3), kept here so the whole knob set lives in one section.
    "self_improvement": {
        "enabled": False,
        "detect_cadence": 20,
        "detector_tier": 1,
        "max_active_rules": 5,
        "max_magnitude": 0.3,
    },
    # Self-introspection — «Боб знает свой мир» (BOB-017 Phase A). Three read-only
    # capabilities (``inspect_architecture`` / ``read_code`` / ``list_work``) let Bob
    # answer about his OWN code/architecture/backlog with real beadloom/code/Beads. They
    # are conversation-only (never on the autonomous safe-allowlist) and privacy-guarded
    # on the infra boundary before any read.
    # 🔴 CORRECTED TO FACT (bob-a6b.17; the error is left VISIBLE rather than rewritten
    # after the fact — Issues #49). This said «only ``src``/``tests``/``docs`` are
    # visible, SOUL/``bob.db``/``.env``/``config`` are DENIED» — the invariant from
    # BEFORE BOB-067, which deliberately widened reading to the WHOLE repo (the owner's
    # call: Bob is an equal engineer, not a whitelist tourist). Today ``config/`` and
    # ``data/`` ARE readable; what the guard refuses is an escape past the repo root,
    # key material anywhere in the tree and the ``.git`` subtree, and every returned
    # byte is sanitised of secret-shaped VALUES. The enumeration lives in ONE place —
    # :mod:`bob.capabilities.introspection.privacy_guard` — and is not copied here.
    # ``enabled`` defaults TRUE (read-only, owner-only chat): on → the three skills are
    # advertised.
    # ``max_output_chars`` caps each tool's output, ``read_max_lines`` caps a file read,
    # and ``beadloom_bin`` / ``bd_bin`` name the local read-only CLIs the subprocess
    # adapter runs against its fixed allowlist (never a shell). ``dev_tools`` (BOB-081)
    # is a SUB-flag, default FALSE: the read-only dev-introspection tools (``recent_commits``
    # git history + ``list_tasks`` / ``show_task`` / ``task_comments`` tracker reads) are
    # registered ONLY when it is on — off → Bob never sees them (zero behaviour change).
    # ``architecture_tools`` (BOB-091) is the second SUB-flag, also default FALSE: the
    # read-only ARCHITECTURE tools register only when it is on — ``draw_architecture``
    # (the mermaid source of the graph, paired with ``render_diagram`` for the picture),
    # ``architecture_impact`` («что сломается, если тронуть X») and ``project_health``
    # (BOB-091.2: one of six read-only project-state reports — status / prime / doctor /
    # sync-check / lint / diff).
    "introspection": {
        "enabled": True,
        "dev_tools": False,
        "architecture_tools": False,
        "max_output_chars": 20000,
        "read_max_lines": 200,
        "beadloom_bin": "beadloom",
        "bd_bin": "bd",
    },
    # Diagram rendering — «Боб рисует» (BOB-035 + BOB-037). The ``render_diagram`` skill
    # takes a Mermaid source, renders it to a PNG LOCALLY via the mermaid-cli (``mmdc``),
    # and posts it to chat. BOB-037 also AUTO-RENDERS any fenced ```mermaid block the
    # model writes into its TEXT reply (the model unreliably calls the tool), so diagrams
    # are reliable either way. It is ``permission=safe`` and renders ONLY its input (no
    # personal data), and the render runs strictly on-machine (privacy — the diagram
    # source never leaves the host). ``enabled`` defaults TRUE (safe + local);
    # ``mmdc_bin`` names the local mermaid-cli binary (a documented runtime dependency —
    # install ``@mermaid-js/mermaid-cli``); ``timeout`` caps one render in seconds so a
    # stuck process cannot wedge a turn. BOB-037 readability knobs: ``scale`` is mmdc's
    # deviceScaleFactor (3x → crisp, not blurry); ``background`` is the page background
    # (``white`` → readable on Telegram's dark theme); ``send_as`` is ``document`` (the
    # default — the PNG is sent UNCOMPRESSED at full resolution, since ``send_photo``
    # recompresses to JPEG and caps ~1280px) or ``photo`` (the inline-preview photo).
    "diagrams": {
        "enabled": True,
        "mmdc_bin": "mmdc",
        "timeout": 30,
        "scale": 3,
        "background": "white",
        "send_as": "document",
    },
    # Coding sessions — «Боб запускает Claude Code», гейтед (BOB-039). The master
    # switch ``enabled`` is OFF by default (conservative — Bob driving a code agent is
    # the most powerful capability, so the owner switches it on deliberately, like
    # goals/self_improvement). When off, the ``/code`` commands are inert (a clear
    # "disabled" reply) and the assistant is never wired. ``claude_bin`` / ``gh_bin``
    # name the local CLIs the shell-free adapters run; ``worktree_root`` is where the
    # isolated per-session git worktrees are created (only TRACKED files, so Bob's
    # private data never reaches Claude Code); ``timeout`` bounds one run (seconds);
    # ``permission_mode`` is the execute-mode passed to ``claude`` after the owner
    # approves the plan (``acceptEdits`` — apply edits in the worktree; NEVER a
    # bypass mode). The plan gate (plan-mode first, no edits) is unbypassable above
    # this config, and there is NO merge / push-to-main path anywhere.
    "coder": {
        "enabled": False,
        "claude_bin": "claude",
        "gh_bin": "gh",
        "worktree_root": ".worktrees",
        "timeout": 600,
        "permission_mode": "acceptEdits",
        # Firehose channel (BOB-087.A1): route the mechanical coder/interactive stream AS
        # GUPPI (through GUPPI's bot) instead of Bob's bot. Default OFF → the stream stays on
        # Bob's bot exactly as today (byte-identical); Bob's own voice (gate lines) always
        # stays on Bob's bot. ON requires the owner to have started GUPPI's bot for a DM target.
        "stream_via_guppi": False,
        # 🔴 Owner-only sandbox relaxations (BOB-087.D2) — both ship INERT, and both make
        # the isolated worktree less isolated, so the owner opts in deliberately (the
        # BOB-076 lesson: a powerful capability is OFF by default).
        # ``allow_bypass`` admits ``bypassPermissions`` into the runner's ``--permission-mode``
        # allowlist (claude stops asking before each edit — fast, but no per-action gate);
        # OFF → the allowlist is exactly {plan, acceptEdits}, the shipped guarantee.
        # ``extra_dirs`` passes ``--add-dir`` paths to claude, i.e. directories OUTSIDE the
        # worktree (and outside the tracked-files-only copy that keeps Bob's private data away
        # from Claude Code); empty → nothing is passed and the argv is byte-identical.
        #
        # 🔴 WHAT ``allow_bypass: true`` REALLY COSTS (be honest — BOB-087.D5b, M4). Bob's own
        # code has no push / merge / PR path in the interactive seam, and that stays true. But
        # ``bypassPermissions`` gives claude an UNSUPERVISED shell inside a LINKED worktree,
        # and a linked worktree shares the main repo's ``.git``: the same objects, the same
        # REFS, the same remotes and the same credentials. From there ``git push --force
        # origin HEAD:main``, ``git branch -f main …`` or ``gh pr merge`` are all expressible.
        # So with this flag ON, «main is untouchable» (INV-2) stops being a STRUCTURAL
        # guarantee and becomes trust in the model plus the owner's judgement. With it OFF —
        # the default — every write claude makes still passes a per-action gate, and that is
        # what actually keeps the trunk safe.
        "allow_bypass": False,
        "extra_dirs": [],
        # 🔴 ДОЛГОЖИВУЩЕЕ рабочее место + возобновление сессии (BOB-087.D3, D5b): owner из
        # лички явной командой ``/workspace <name> [task]`` (или ``/code -w``) заводит
        # персистентный worktree, где работа НАКАПЛИВАЕТСЯ между сеансами; команда
        # ``/resume <workspace>`` (``/code -r``) поднимает в нём прошлую сессию через
        # ``claude --resume <id>``. Ship OFF: живой claude, приземляющийся в уже
        # накопленное дерево, — самое мощное действие интерактива, и по уроку BOB-076
        # такое включается сознательно. OFF → ни одна из команд не распознаётся,
        # персистентный worktree не создаётся, поведение байт-в-байт как в BOB-083.
        # Предохранители на ON: owner-only + DM-only, для подъёма ещё и явное
        # подтверждение в окне TTL; поднять можно ТОЛЬКО остановленную сессию (не
        # live-attach); ни push, ни merge, ни PR тут не выразимы — main только через PR.
        # Оговорка та же, что и для ``allow_bypass`` выше: структурной эта гарантия
        # остаётся, пока сам claude работает под пер-действенным гейтом.
        "resume": False,
        # 🔴 THE WORKPLACE AS A SEPARATE CLONE (BOB-089, slice A), ships OFF. A linked
        # worktree SHARES the main repo's ``.git`` — the same objects, the same REFS, the
        # same remotes and credentials — so ``git update-ref refs/heads/main <sha>`` moves
        # the owner's trunk with no network and no credentials, bypassing every push guard
        # (verified on real git, bob-5ao). ON → Bob works in a clone with its OWN ``.git``
        # and that road does not exist at all; privacy is unchanged (a clone carries only
        # TRACKED files — proven on real git, not assumed). ``clone_root`` is where the
        # clones live (relative to the repo root, gitignored); ``fork_url`` is the clone's
        # ONLY remote (Bob's fork) — empty means the clone has no remote whatsoever.
        # 🔴 CORRECTED TO FACT (TWICE) (bob-a6b.17; both errors left VISIBLE rather than
        # rewritten after the fact — Issues #49). This comment said two things that are no
        # longer true, and both had already been settled elsewhere in this very epic:
        #   1. «the upstream is never configured under any value» — the SIXTH survival of a
        #      claim the reviewer disproved on real git (bob-a6b.6, MAJOR-7/8): the model
        #      writes ``remote.origin.pushurl`` into the clone's LOCAL config on top of our
        #      argv, and ``url.<upstream>.pushInsteadOf`` carries the branch upstream even
        #      when we push BY VALUE. True in the narrow form only: AT CLONE SETUP the
        #      upstream is configured under no value of ``fork_url``. What the directory
        #      looks like afterwards is the model's business, which is why the branch goes
        #      out by VALUE and an unknown local-config key stops integration
        #      (:func:`bob.coding.untrusted_repo.unsafe_local_config`).
        #   2. «this flag does NOT isolate CREDENTIALS (a separate slice)» — stale in the
        #      OPPOSITE direction: slice C shipped that isolation under THIS SAME flag
        #      (:func:`bob.runtime.wiring.coding._build_spawn_isolation`). Clone + spawn
        #      isolation are two halves of one guarantee — the clone closes the LOCAL road
        #      to the trunk (its own ``.git``), the isolation the AMBIENT network one — so
        #      there is deliberately one flag. What is still on trust (same UID: a direct
        #      ``ssh``, a filesystem path to the owner's repo) is named in
        #      ``docs/domains/identity/README.md``, not hidden — bead BOB-093.
        # 🔴 And a token is NEVER embedded in ``fork_url``
        # (``https://x-access-token:<token>@host/…``): argv is visible in ``ps``, so such a
        # configuration is refused at startup. Measured price on this repository: 3.8 s and
        # 142 MB per workplace.
        # 🔴 ``fork_url`` (transport) and ``github.work_repo`` (the API slug of the same fork)
        # are two ANGLES of ONE repository, not a duplicate — an ssh address cannot be derived
        # from a slug. They MUST agree, and that is CHECKED when the handover link is
        # assembled (a mismatch is refused loudly, naming both keys), rather than left as the
        # owner's discipline: divergence would push the branch to one repository, promise the
        # owner a second and hold rights to a third.
        # 🔴 CORRECTED TO FACT AGAIN, 2026-08-15 (bob-c3r.1, P0 bob-l3t; the change is left
        # VISIBLE). This line used to read ``"isolated_clone": False`` — the clone was
        # OPT-IN, and switching it on lived in ``config/bob.yaml``, which is GITIGNORED. So
        # on a fresh clone, on any other machine, and for anyone reading the repository the
        # protection was OFF, while a live claude terminal ran inside the OWNER's linked
        # worktree. A guarantee held by an untracked file is not a guarantee.
        # The key is now DELIBERATELY ABSENT from these defaults so there is exactly ONE
        # place that answers it — :func:`bob.runtime.wiring.coding._uses_isolated_clone`,
        # which defaults to the isolated clone (ON) and refuses a value that is neither an
        # explicit yes nor an explicit no. Two defaults for one safety fact would one day
        # diverge, and the honest-looking one would be the stale one. The owner opts OUT
        # explicitly: ``coder.isolated_clone: false``.
        "clone_root": ".clones",
        "fork_url": "",
        # 🔴 BOB'S OWN IDENTITY IN THE HISTORY (BOB-089, slice D), blank by default so
        # nothing changes until the clone workplace is switched on. ``app_user_id`` is the
        # NUMERIC GitHub App user id that prefixes the bot's noreply address in Bob's commits
        # (``<id>+bob-ai-work[bot]@users.noreply.github.com``); blank → the address carries no
        # prefix, while the NAME (``bob[ai]``) is set either way, because not signing at all
        # would have git fall back to the OWNER's identity — exactly the confusion this slice
        # removes. The signature is written ``--local``, in Bob's clone only: a global setting
        # would re-sign the owner's own commits. This id is public information, unlike a
        # token — it may live in argv.
        # 🔴 THE UPSTREAM OF THE COMPARE LINK IS **NOT** HERE (bob-a6b.9). It is
        # ``github.propose_repo`` — the ONE section that owns repository identity, and the
        # same slug the ``propose`` principal reads the upstream with. An earlier
        # ``coder.upstream_repo`` said the same thing a second time; two keys for one fact
        # eventually diverge, and then Bob hands over a link to one repository while holding
        # read rights to another.
        "app_user_id": "",
    },
    # 🔴 BOB'S GITHUB IDENTITY (BOB-089, slice B) — «who he presents himself as, and what he
    # authenticates with». Everything ships EMPTY: with no credentials the ``bob.identity``
    # module is inert, and the refusal names the MISSING CONFIG KEY at the moment a token is
    # actually needed (building the provider on an unconfigured Bob never fails).
    #
    # There are TWO principals because a GitHub App's permissions are identical for ALL of
    # its installations — they cannot be narrowed «for this one repository». ``work``
    # («Bob AI Work», contents write, installed ONLY on the organisation holding the private
    # fork) pushes Bob's branch and cannot write a single byte to the owner's upstream;
    # ``propose`` («Bob AI Propose», contents READ + pull_requests write) reads the upstream
    # (owner's negative smoke: create a branch / force-push main / write a file upstream —
    # all three 403 «Resource not accessible by integration»).
    #
    # Three keys per principal: ``_app_id`` (numeric; travels in the App JWT ``iss`` claim),
    # ``_app_key`` — 🔴 the PATH to the private key (``.secrets/*.pem``, 0600), NEVER the key
    # material itself: that would land in openssl's argv, and argv is visible in ``ps``; and
    # ``_repo`` — the ``owner/repo`` whose INSTALLATION this principal uses (an installation
    # token is scoped to ONE installation). Values come from ``.env``
    # (``BOB_GITHUB__WORK_APP_ID`` …), never from the repository.
    #
    # 🔴 THIS SECTION IS THE SINGLE SOURCE OF REPOSITORY IDENTITY (bob-a6b.9). ``work_repo``
    # is Bob's private fork, ``propose_repo`` is the owner's upstream — and ``propose_repo``
    # is therefore ALSO the target of the compare link Bob hands over when his work is ready
    # (he does NOT open the PR: a cross-repo PR from a PRIVATE fork is not expressible for an
    # installation token — three ways verified, a non-goal). Blank (or no fork / no clone) →
    # the previous ``gh pr create`` path, byte-identical.
    #
    # ``token_margin_seconds`` — 🔴 renew AHEAD of time, not on a 401: an installation token
    # lives one hour, a coder session can run longer, and breaking mid-work would cost far
    # more than one extra mint. ``jwt_lifetime_seconds`` — the App JWT lifetime, comfortably
    # inside GitHub's ten-minute ceiling.
    "github": {
        "work_app_id": "",
        "work_app_key": "",
        "work_repo": "",
        "propose_app_id": "",
        "propose_app_key": "",
        "propose_repo": "",
        # The three durations are floats: the adapter reads them as such, and an env
        # value is coerced to the default's type (BOB-116).
        "token_margin_seconds": 300.0,
        "jwt_lifetime_seconds": 480.0,
        "api_base_url": "https://api.github.com",
        "openssl_bin": "openssl",
        "timeout_seconds": 30.0,
    },
    # Web search — «Боб ищет в интернете» (BOB-053). The ``web_search`` skill (behind
    # the capability seam) makes ONE Qwen-native call over the MaaS **Responses API**
    # (``/responses``, ``tools:[web_search]``) and returns a grounded answer + sources
    # (verify .1: this is the only path that returns clickable sources on the workspace
    # key). ``enabled`` defaults TRUE — the skill is read-only and gated by sender authz
    # (owner-only; the tool-loop never runs for an unauthorised sender), so it can be
    # advertised by default. ``model`` is the Qwen-native search model. ``base_url`` /
    # ``api_key`` are BLANK by default and fall back to the Tier-1 Qwen MaaS host + key
    # (``llm.tier1_*`` — the same workspace ``sk`` key, no separate/global key needed);
    # set them only to point search at a different host/key. ``timeout_seconds`` is
    # generous because a Responses-API search is slow (several seconds).
    "search": {
        "enabled": True,
        "model": "qwen3.7-plus",
        "base_url": "",
        "api_key": "",
        "timeout_seconds": 180.0,  # a float: the factory reads it as one (BOB-116)
    },
    # Read a link — «Боб читает присланную ссылку» (BOB-054). The ``read_url`` skill
    # (behind the capability seam, twin of ``web_search``) makes ONE ``aiohttp`` GET
    # through a 🔴 SSRF-guarded reader (http/https only, every resolved IP must be
    # public, manual re-validated redirects, streaming byte cap, content-type allowlist)
    # and returns the page's extracted readable text. ``enabled`` defaults TRUE — it is
    # read-only and gated by sender authz (owner-only; the tool-loop never runs for an
    # unauthorised sender). ``timeout_seconds`` bounds a slow host; ``max_bytes`` aborts
    # a giant/endless body mid-stream; ``max_redirects`` caps redirect hops (each hop is
    # re-validated by the SSRF guard); ``max_chars`` truncates the extracted text fed to
    # the model; ``user_agent`` is the fixed UA sent on every request (no auth headers).
    "read_url": {
        "enabled": True,
        "timeout_seconds": 15.0,  # a float: the reader factory reads it as one (BOB-116)
        "max_bytes": 2_000_000,
        "max_redirects": 5,
        "max_chars": 10_000,
        "user_agent": "BobBot/0.1 (+https://github.com/vzoologov/bob)",
    },
    # Pre-answer epistemic verify — «Боб знает, чего не знает» (BOB-057). BEFORE Bob
    # answers, a conservative Tier-0 ``VolatilityJudge`` decides whether the answer hinges
    # on a FRESH, fast-decaying fact (rates/prices/«сейчас»/standings/versions…); on a
    # ``needs_check`` it makes ONE DIRECT ``web_search`` (reusing the ``search`` provider)
    # and folds the finding into the reply, hedging honestly on failure. 🔴 The call is
    # DIRECT (not the capability registry / tool-loop) → NOT the BOB-052 per-sender gate:
    # an internal public-verify that exposes only PUBLIC web info, works for owner and
    # guest alike, and does NOT weaken BOB-051/052 on user-facing tool requests.
    # ``enabled`` defaults TRUE (matching the shipped read-only web skills) — note it makes
    # a background search happen on a volatile-fact turn; set FALSE to make the seam fully
    # inert. ``timeout_seconds`` is SHORTER than the deep ``search`` timeout so a slow
    # search hedges rather than stalls the turn. The provider itself is built from the
    # ``search`` section (same Qwen web_search).
    "verify": {
        "enabled": True,
        "timeout_seconds": 75,
    },
    # Two bots in one process (BOB-003): Bob lives in his topic, GUPPI is the
    # gatekeeper in General. Each bot's token comes from env only (never YAML);
    # the shared ids (chat/owner/allowlist) and Bob's topic are non-secret.
    "telegram": {
        "poll_timeout": 10,
        "chat_id": 0,
        "owner_id": 0,
        # The owner's display name, used ONLY by the BOB-045 best-effort backfill to
        # attribute legacy NULL-sender episodes whose content prefix is this name to
        # owner_id. Empty (the default) -> the backfill is a graceful no-op.
        "owner_name": "",
        "allowed_chat_ids": [],
        "bob": {
            "token": "",
            "topic_id": 0,
        },
        "guppi": {
            "token": "",
        },
    },
}


class ConfigLoader:
    """Build the effective configuration from defaults, an optional YAML, env."""

    def __init__(
        self,
        *,
        yaml_path: Path | None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._yaml_path = yaml_path
        self._env = dict(env) if env is not None else dict(os.environ)

    def load(self) -> Config:
        """Return the merged configuration (defaults <- YAML <- env)."""
        config: Config = copy.deepcopy(DEFAULT_CONFIG)
        _deep_merge(config, self._load_yaml())
        _deep_merge(config, self._load_env())
        self._apply_token_mapping(config)
        return config

    def _load_yaml(self) -> Config:
        if self._yaml_path is None or not self._yaml_path.is_file():
            return {}
        raw = yaml.safe_load(self._yaml_path.read_text(encoding="utf-8"))
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise ValueError(f"config YAML root must be a mapping, got {type(raw).__name__}")
        return dict(raw)

    def _load_env(self) -> Config:
        overrides: Config = {}
        for key, value in self._env.items():
            # The explicitly mapped bot tokens are applied separately (with their
            # own nested path); skip them so the generic rule doesn't misplace one.
            if key in _TOKEN_ENV_MAPPING or not key.startswith(_ENV_PREFIX):
                continue
            path = key[len(_ENV_PREFIX) :].lower().split(_ENV_NESTING_SEPARATOR)
            typed = coerce_env_value(
                key,
                path,
                value,
                defaults=DEFAULT_CONFIG,
                list_element_types=_LIST_ELEMENT_TYPES,
            )
            _assign_nested(overrides, path, typed)
        return overrides

    def _apply_token_mapping(self, config: Config) -> None:
        """Overlay the two bot tokens from their explicit env vars (env wins)."""
        for env_var, path in _TOKEN_ENV_MAPPING.items():
            value = self._env.get(env_var)
            if value is not None:
                _assign_nested(config, list(path), value)


def _deep_merge(base: MutableMapping[str, Any], overlay: Mapping[str, Any]) -> None:
    """Recursively merge ``overlay`` into ``base`` in place."""
    for key, value in overlay.items():
        existing = base.get(key)
        if isinstance(existing, MutableMapping) and isinstance(value, Mapping):
            _deep_merge(existing, value)
        else:
            base[key] = value


def _assign_nested(target: Config, path: list[str], value: object) -> None:
    """Assign ``value`` into ``target`` at the nested ``path`` of keys."""
    cursor: MutableMapping[str, Any] = target
    for segment in path[:-1]:
        nxt = cursor.get(segment)
        if not isinstance(nxt, MutableMapping):
            nxt = {}
            cursor[segment] = nxt
        cursor = nxt
    cursor[path[-1]] = value
