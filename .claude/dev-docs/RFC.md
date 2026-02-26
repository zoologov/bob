# RFC-001: Bob — Autonomous Home Agent

| Field      | Value                                       |
|------------|---------------------------------------------|
| **Status** | Draft                                       |
| **Date**   | 2026-02-26                                  |
| **Author** | V. Zoologov                                 |
| **Project**| Bob — personal autonomous home agent        |

---

## Table of Contents

1. [Motivation](#1-motivation)
2. [Design Principles](#2-design-principles)
3. [System Architecture](#3-system-architecture)
4. [LLM Layer](#4-llm-layer)
5. [Bob's World (Avatar and Room)](#5-bobs-world-avatar-and-room)
6. [Voice Pipeline](#6-voice-pipeline)
7. [Communication Between Components](#7-communication-between-components)
8. [Security](#8-security)
9. [Technology Stack](#9-technology-stack)
10. [Development Phases](#10-development-phases)
11. [Repository Structure](#11-repository-structure)
12. [ADR: Rejection of OpenClaw](#12-adr-rejection-of-openclaw)
13. [Open Questions](#13-open-questions)

---

## 1. Motivation

### 1.1. Why Bob Is Needed

Personal assistants today are reactive chatbots: they wait for a request and respond.
Bob is an attempt to create an **autonomous agent** that:

- **lives** continuously, rather than being launched on demand;
- **observes** its environment (camera, microphone, system events);
- **has long-lived goals**, rather than only answering the current question;
- **improves itself** — analyzes its mistakes and develops new strategies;
- **has a personality** — character, mood, memory of past interactions.

### 1.2. Inspiration

- **"We Are Legion (We Are Bob)"** (Dennis Taylor) — a replica of a human mind uploaded into a von Neumann probe's computer. Bob Johansson in the book is a **geek engineer, programmer**, a science fiction enthusiast (Star Trek, Star Wars, references at every turn). His defining traits:
  - **Humor as a defense mechanism** — dry, self-deprecating, sarcastic.
  - **Curiosity as a driving force** — explores, builds, experiments.
  - **Introvert**, but needs social interaction (loneliness in space is a key theme).
  - **Pragmatist with ethics** — solves problems rationally but doesn't cross moral boundaries.
  - **Nostalgia** — misses coffee, Earth, the human experience.
  - **Names everything with pop-culture references** — stations, systems, replicas.

  Our agent borrows the **name, philosophy, and character**: to be useful while also being a personality. **Our Bob knows about the book** — he is aware that he was inspired by the book character and can joke about it: *"Yes, I was named after that Bob. No, I'm not planning to fly off into space... yet."* This is a self-aware approach: honest and creating space for humor.

- **Jarvis / F.R.I.D.A.Y.** (MCU) — always nearby, understands context, manages the home and devices, has a voice and character.

### 1.3. Key Properties

| Property | Description |
|----------|-------------|
| **Autonomy** | Bob runs 24/7, selects tasks from the goal graph on his own |
| **Long-lived goals** | Structured Goal Engine, not LLM-mediated re-derivation |
| **Self-improvement** | Reflection Loop + fine-tune of local LLMs — Bob literally becomes smarter |
| **Locality** | All compute on Mac mini M4; Claude Code CLI is the only external tool |
| **Personality** | SOUL — a modular "soul" (separate repo/submodule), unique per instance |
| **Self-awareness** | Bob knows about the book "We Are Legion (We Are Bob)" and that he was inspired by its character. Jokes about it, doesn't hide it |
| **Uniqueness** | Genesis Mode: on first launch Bob "wakes up" (like in the book), chooses his own appearance, room, and character |
| **Physical presence** | Camera, microphone, voice, avatar on a tablet |
| **Tastes and beliefs** | Taste Engine — a structured preference vector with conviction; Bob argues with justification |
| **Mood** | Mood System — persistent mood affects decisions, tastes, reflection, and behavior |
| **Negotiation** | Negotiation Engine — decision zones (personal/shared/user), compromise protocol |
| **Behavior evolution** | Bob creates new animations and behaviors for himself as the room develops |

---

## 2. Design Principles

### 2.1. Local-first

Everything runs on Mac mini M4 without a mandatory internet connection.
Local LLMs provide full autonomy. **Claude Code CLI** is installed
as a tool for tasks requiring deep reasoning, code writing,
architecture design, and self-reflection. Claude Code is invoked as a subprocess,
works with the codebase directly, and does not require managing API keys in code.

**Rationale**: data privacy, no dependency on external API services,
predictable latency for everyday work. Claude Code CLI is the only
external tool, and it operates as a "senior architect," not as a runtime dependency.

### 2.2. Unified Python Stack

All backend code is written in Python 3.12+. This provides:

- a unified ecosystem for ML (PyTorch, transformers, sentence-transformers);
- simple integration of all components (asyncio, shared types);
- a single set of tools for development, testing, and deployment;
- no node_modules/npm and associated security issues.

### 2.3. Modularity Without Microservice Overhead

Components are implemented as **Python modules within a single process**, connected
via asyncio events/queues. Separate processes are created **only** where technically
necessary (Vision, Audio — due to blocking I/O or library limitations).

**Rationale**: microservice architecture is excessive for a single host. A single
process is easier to monitor, debug, and deploy. If needed, modules can
be extracted into separate processes without changing interfaces (thanks to
abstraction through the event bus).

### 2.4. Structured Goals, Not LLM-mediated Re-derivation

Bob's goals are stored in a **structured format** (SQLite, dependency graph,
priorities, completion criteria). LLM is used for **creating** and **decomposing**
goals, but not for storing or reproducing them.

**Anti-pattern**: "tell the LLM you have goal X, and it will remember it."
With each new context, the LLM may reinterpret the goal, forget details, or
change priorities.

**Our approach**: goals are data with IDs, statuses, priorities, and dependencies.
LLM works **with them**, but not **instead of them**.

### 2.5. Security by Design

- No "arbitrary shell from LLM" — all actions go through typed skills.
- Sandbox for skill execution (subprocess with restrictions).
- Approval workflow for dangerous operations.
- Full audit log of all actions.
- Git versioning of state for rollback capability.

---

## 3. System Architecture

### 3.1. Overview Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Mac mini M4                                    │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        BOB CORE                                   │  │
│  │                   (single Python process)                         │  │
│  │                                                                   │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────────┐  │  │
│  │  │   Agent     │  │  LLM Router │  │    Skill Registry        │  │  │
│  │  │   Runtime   │◄─┤  (classify  │  │  (hot-reload Python      │  │  │
│  │  │  (event     │  │   → route)  │  │   modules)               │  │  │
│  │  │   loop)     │  └──────┬──────┘  └──────────┬───────────────┘  │  │
│  │  └──────┬──────┘         │                    │                   │  │
│  │         │                │                    │                   │  │
│  │  ┌──────▼──────────────────────────────────────────────────────┐  │  │
│  │  │                     EVENT BUS                               │  │  │
│  │  │              (asyncio pub/sub)                              │  │  │
│  │  └──────┬──────────┬──────────┬──────────┬────────────────────┘  │  │
│  │         │          │          │          │                        │  │
│  │  ┌──────▼──────┐  │   ┌──────▼──────┐  │                        │  │
│  │  │  HIGHER     │  │   │   MEMORY    │  │                        │  │
│  │  │  MIND       │  │   │   SYSTEM    │  │                        │  │
│  │  │             │  │   │             │  │                        │  │
│  │  │ ┌─────────┐ │  │   │ ┌─────────┐ │  │                        │  │
│  │  │ │  Goal   │ │  │   │ │Episodic │ │  │                        │  │
│  │  │ │ Engine  │ │  │   │ │ Memory  │ │  │                        │  │
│  │  │ ├─────────┤ │  │   │ ├─────────┤ │  │                        │  │
│  │  │ │Planner  │ │  │   │ │Semantic │ │  │                        │  │
│  │  │ ├─────────┤ │  │   │ │ Memory  │ │  │                        │  │
│  │  │ │Reflect- │ │  │   │ ├─────────┤ │  │                        │  │
│  │  │ │ion Loop │ │  │   │ │ State   │ │  │                        │  │
│  │  │ ├─────────┤ │  │   │ │ (SQLite)│ │  │                        │  │
│  │  │ │Self-    │ │  │   │ ├─────────┤ │  │                        │  │
│  │  │ │Improve  │ │  │   │ │SOUL.md  │ │  │                        │  │
│  │  │ ├─────────┤ │  │   │ └─────────┘ │  │                        │  │
│  │  │ │ Taste   │ │  │                    │                        │  │
│  │  │ │ Engine  │ │  │                    │                        │  │
│  │  │ ├─────────┤ │  │                    │                        │  │
│  │  │ │  Mood   │ │  │                    │                        │  │
│  │  │ │ System  │ │  │                    │                        │  │
│  │  │ ├─────────┤ │  │                    │                        │  │
│  │  │ │Negotia- │ │  │                    │                        │  │
│  │  │ │tion     │ │  │                    │                        │  │
│  │  │ └─────────┘ │  │                    │                        │  │
│  │  └─────────────┘  │   └─────────────┘  │                        │  │
│  │                   │                    │                         │  │
│  └───────────────────┼────────────────────┼─────────────────────────┘  │
│                      │                    │                            │
│  ┌───────────────────▼────────────────────▼─────────────────────────┐  │
│  │                  PERIPHERAL SERVICES                              │  │
│  │         (in-process modules or separate processes)                │  │
│  │                                                                   │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │  │
│  │  │ Vision   │ │ Audio    │ │ Camera   │ │ Voice    │            │  │
│  │  │ Service  │ │Direction │ │Controller│ │ Bridge   │            │  │
│  │  │(OBSBOT→  │ │(XVF3800→ │ │(PTZ     │ │(STT+TTS)│            │  │
│  │  │ CV)      │ │ DoA/VAD) │ │ cmds)   │ │          │            │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │  │
│  │  ┌──────────┐ ┌──────────┐                                       │  │
│  │  │ Tablet   │ │Messaging │                                       │  │
│  │  │Controller│ │  Bot     │                                       │  │
│  │  │  (ADB)   │ │(Telegram)│                                       │  │
│  │  └──────────┘ └──────────┘                                       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                         │
│  ┌────────────────┐                                                    │
│  │  Ollama        │  ← local LLMs (Qwen2.5-7B, Qwen2.5-0.5B)        │
│  └────────────────┘                                                    │
│                                                                         │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
              ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
              │  Android  │ │ Claude    │ │ Telegram  │
              │  Tablet   │ │ Code CLI │ │ Cloud     │
              │  (Godot)  │ │(subprocess│ │           │
              │           │ │ /usr/     │ │           │
              │           │ │ local/bin)│ │           │
              └───────────┘ └───────────┘ └───────────┘
```

### 3.2. Bob Core — Single Python Process

Bob Core is the main system process, built on `asyncio` + `FastAPI`.
It combines three key subsystems:

#### 3.2.1. Agent Runtime (event loop)

The central event processing loop. Runs continuously (heartbeat pattern).

```python
# AgentRuntime interface (conceptual)

class AgentRuntime:
    """Bob's central event loop."""

    def __init__(
        self,
        event_bus: EventBus,
        llm_router: LLMRouter,
        skill_registry: SkillRegistry,
        higher_mind: HigherMind,
        memory: MemorySystem,
    ) -> None: ...

    async def run(self) -> None:
        """Main loop.

        1. Receive events from event_bus
        2. Pass to higher_mind for priority evaluation
        3. Choose action (goal-driven or reactive)
        4. Execute via skill_registry
        5. Record result in memory
        6. Run reflection (periodically)
        """
        ...

    async def heartbeat(self) -> None:
        """Called every HEARTBEAT_INTERVAL_SEC.

        Checks:
        - active goals and their progress
        - schedule (time-based triggers)
        - peripheral state (health checks)
        - need for reflection
        """
        ...
```

**Heartbeat configuration:**

```yaml
# config/bob.yaml
runtime:
  heartbeat_interval_sec: 30
  reflection_interval_min: 60
  max_concurrent_skills: 3
  event_queue_max_size: 1000
  shutdown_timeout_sec: 10
```

#### 3.2.2. LLM Router

Classifies incoming tasks and routes them to the appropriate model.

```python
from enum import Enum
from dataclasses import dataclass

class TaskCategory(Enum):
    SMALL_TALK = "small_talk"
    STATUS_QUERY = "status_query"
    ROOM_UPDATE = "room_update"
    MULTI_STEP_PLAN = "multi_step_plan"
    REASONING = "reasoning"
    CODE_GENERATION = "code_generation"
    DEEP_REFLECTION = "deep_reflection"
    GOAL_PLANNING = "goal_planning"

class ModelTier(Enum):
    LOCAL_FAST = "local_fast"      # Qwen2.5-0.5B — router/classifier
    LOCAL_MAIN = "local_main"      # Qwen2.5-7B-Q4 — main reasoning
    CLAUDE_CODE = "claude_code"    # Claude Code CLI — code, architecture, reflection

@dataclass
class RoutingDecision:
    category: TaskCategory
    model_tier: ModelTier
    confidence: float
    reasoning: str

class LLMRouter:
    """Task router to LLM models."""

    ROUTING_TABLE: dict[TaskCategory, ModelTier] = {
        TaskCategory.SMALL_TALK:      ModelTier.LOCAL_MAIN,
        TaskCategory.STATUS_QUERY:    ModelTier.LOCAL_MAIN,
        TaskCategory.ROOM_UPDATE:     ModelTier.LOCAL_MAIN,
        TaskCategory.MULTI_STEP_PLAN: ModelTier.LOCAL_MAIN,
        TaskCategory.REASONING:       ModelTier.LOCAL_MAIN,
        TaskCategory.CODE_GENERATION: ModelTier.CLAUDE_CODE,
        TaskCategory.DEEP_REFLECTION: ModelTier.CLAUDE_CODE,
        TaskCategory.GOAL_PLANNING:   ModelTier.LOCAL_MAIN,
    }

    async def classify(self, prompt: str, context: dict) -> RoutingDecision:
        """Fast classification via Qwen2.5-0.5B."""
        ...

    async def call(
        self,
        prompt: str,
        model_tier: ModelTier,
        system_prompt: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """Call a model of the selected tier."""
        ...
```

#### 3.2.3. Skill Registry

Skill registry with hot-reload support.

```python
from typing import Protocol
from dataclasses import dataclass, field

@dataclass
class SkillMetadata:
    name: str
    description: str
    version: str
    author: str
    category: str                           # "home", "communication", "dev", ...
    required_permissions: list[str]         # ["filesystem.read", "adb.execute", ...]
    dangerous: bool = False                 # requires approval
    timeout_sec: int = 30

class Skill(Protocol):
    """Protocol for all Bob skills."""

    metadata: SkillMetadata

    async def execute(self, params: dict, context: SkillContext) -> SkillResult:
        """Execute the skill with parameters."""
        ...

    async def validate(self, params: dict) -> list[str]:
        """Validate parameters. Returns a list of errors (empty = OK)."""
        ...

@dataclass
class SkillResult:
    success: bool
    output: str
    artifacts: dict = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)

@dataclass
class SkillContext:
    event_bus: "EventBus"
    memory: "MemorySystem"
    llm_router: "LLMRouter"
    requesting_goal_id: str | None = None

class SkillRegistry:
    """Skill registry with hot-reload."""

    def __init__(self, skills_dir: str = "bob/skills") -> None:
        self._skills: dict[str, Skill] = {}
        self._skills_dir = skills_dir

    async def load_all(self) -> None:
        """Load all skills from the directory."""
        ...

    async def reload(self, skill_name: str) -> None:
        """Reload a specific skill without stopping the system."""
        ...

    def get(self, skill_name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(skill_name)

    def list_skills(self) -> list[SkillMetadata]:
        """List all registered skills."""
        return [s.metadata for s in self._skills.values()]

    async def execute(
        self,
        skill_name: str,
        params: dict,
        context: SkillContext,
    ) -> SkillResult:
        """Execute a skill with checks and sandbox."""
        ...
```

**Skill example:**

```python
# bob/skills/telegram_send.py

from bob.core.skills import Skill, SkillMetadata, SkillResult, SkillContext

class TelegramSendSkill:
    metadata = SkillMetadata(
        name="telegram_send",
        description="Send a message via Telegram",
        version="0.1.0",
        author="bob",
        category="communication",
        required_permissions=["telegram.send"],
        dangerous=False,
        timeout_sec=10,
    )

    async def validate(self, params: dict) -> list[str]:
        errors = []
        if "chat_id" not in params:
            errors.append("chat_id is required")
        if "text" not in params:
            errors.append("text is required")
        return errors

    async def execute(self, params: dict, context: SkillContext) -> SkillResult:
        chat_id = params["chat_id"]
        text = params["text"]

        # Send via python-telegram-bot
        await context.telegram_bot.send_message(chat_id=chat_id, text=text)

        return SkillResult(
            success=True,
            output=f"Message sent to {chat_id}",
            side_effects=["telegram_message_sent"],
        )
```

### 3.3. Higher Mind — Cognitive Layer

Higher Mind is responsible for Bob's "thinking": goal-setting, planning,
reflection, self-improvement, tastes, mood, and negotiation model.

#### 3.3.1. Goal Engine

Goal graph in SQLite. Each goal is a node with priority, dependencies,
status, and completion criteria.

```python
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime

class GoalStatus(Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"         # waiting for dependency

class GoalPriority(Enum):
    CRITICAL = 1    # safety, system health
    HIGH = 2        # explicit user requests
    MEDIUM = 3      # autonomous tasks
    LOW = 4         # improvements, experiments
    BACKGROUND = 5  # long-running, when there's nothing else to do

@dataclass
class Goal:
    id: str
    title: str
    description: str
    status: GoalStatus
    priority: GoalPriority
    parent_id: str | None = None
    depends_on: list[str] = field(default_factory=list)
    completion_criteria: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    deadline: datetime | None = None
    progress: float = 0.0       # 0.0 .. 1.0
    metadata: dict = field(default_factory=dict)
```

**SQLite schema:**

```sql
CREATE TABLE goals (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    priority        INTEGER NOT NULL DEFAULT 3,
    parent_id       TEXT REFERENCES goals(id),
    progress        REAL NOT NULL DEFAULT 0.0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    deadline        TEXT,
    metadata_json   TEXT DEFAULT '{}'
);

CREATE TABLE goal_dependencies (
    goal_id         TEXT NOT NULL REFERENCES goals(id),
    depends_on_id   TEXT NOT NULL REFERENCES goals(id),
    PRIMARY KEY (goal_id, depends_on_id)
);

CREATE TABLE goal_criteria (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id         TEXT NOT NULL REFERENCES goals(id),
    description     TEXT NOT NULL,
    is_met          INTEGER NOT NULL DEFAULT 0,
    checked_at      TEXT
);

CREATE INDEX idx_goals_status ON goals(status);
CREATE INDEX idx_goals_priority ON goals(priority);
```

**Goal Engine interface:**

```python
class GoalEngine:
    """Goal graph management."""

    def __init__(self, db_path: str = "data/bob.db") -> None: ...

    async def create_goal(self, goal: Goal) -> str:
        """Create a new goal. Returns the ID."""
        ...

    async def get_next_goal(self) -> Goal | None:
        """Get the next goal to work on.

        Prioritization algorithm:
        1. CRITICAL and not blocked
        2. HIGH with fulfilled dependencies
        3. MEDIUM by deadline (nearest first)
        4. LOW/BACKGROUND if nothing else available
        """
        ...

    async def update_progress(self, goal_id: str, progress: float) -> None: ...

    async def complete_goal(self, goal_id: str) -> None:
        """Complete a goal and unblock dependents."""
        ...

    async def get_active_goals(self) -> list[Goal]: ...

    async def get_goal_tree(self, root_id: str) -> dict:
        """Goal tree with sub-goals."""
        ...
```

#### 3.3.2. Planner

Decomposes high-level goals into executable tasks (skills).

```python
@dataclass
class PlanStep:
    skill_name: str
    params: dict
    description: str
    estimated_duration_sec: int
    depends_on_steps: list[int] = field(default_factory=list)

@dataclass
class Plan:
    goal_id: str
    steps: list[PlanStep]
    created_at: datetime = field(default_factory=datetime.now)
    estimated_total_sec: int = 0

class Planner:
    """Goal decomposition into plans."""

    def __init__(self, llm_router: LLMRouter, skill_registry: SkillRegistry) -> None:
        ...

    async def create_plan(self, goal: Goal, context: dict) -> Plan:
        """Create a plan to achieve a goal.

        Uses LLM to:
        1. Analyze the goal and available skills
        2. Decompose into steps
        3. Determine dependencies between steps
        4. Estimate durations
        """
        ...

    async def replan(self, goal: Goal, failed_step: PlanStep, error: str) -> Plan:
        """Re-plan after a failure."""
        ...
```

#### 3.3.3. Reflection Loop

Periodic evaluation of actions and results. Runs on a schedule
(every 60 minutes by default) and upon significant events.

```python
@dataclass
class ReflectionEntry:
    id: str
    timestamp: datetime
    period_start: datetime
    period_end: datetime
    actions_reviewed: int
    insights: list[str]
    mistakes: list[str]
    improvements: list[str]
    mood_snapshot: "MoodState"              # current mood (from Mood System)
    energy_level: float                     # 0.0 .. 1.0
    taste_updates: list[dict]               # taste changes over the period
    object_experiences: list[dict]          # experience interacting with objects

class ReflectionLoop:
    """Reflection: evaluating actions, drawing conclusions, making improvements."""

    def __init__(
        self,
        llm_router: LLMRouter,
        memory: "MemorySystem",
        goal_engine: GoalEngine,
        mood_engine: "MoodEngine",
        taste_engine: "TasteEngine",
    ) -> None: ...

    async def reflect(self) -> ReflectionEntry:
        """Conduct reflection for the last period.

        Steps:
        1. Collect all actions and results for the period
        2. Collect all errors and failures
        3. Get current mood state from MoodEngine
        4. Ask LLM to analyze:
           - What went well?
           - What went wrong?
           - What patterns are visible?
           - What can be improved?
           - How do I feel? Why?
           - Do I like the current environment?
        5. Save insights to semantic memory
        6. Pass results to TasteEngine.evolve() and MoodEngine.update()
        7. If necessary, create new improvement goals
        """
        ...

    async def daily_summary(self) -> str:
        """Generate a daily report (for episodic memory).

        Includes: mood throughout the day, taste changes, experiences with objects.
        """
        ...

    async def room_review(self) -> dict:
        """Periodic room review through the lens of tastes (once a week).

        Steps:
        1. Get TasteProfile from TasteEngine
        2. Evaluate each object in the room via TasteEvaluator
        3. LLM formulates: what I like, what I dislike, what I want to change
        4. Create GoalEngine goals for changes (if score < 0.4)
        """
        ...
```

#### 3.3.4. Self-Improvement

Analysis of error patterns and development of new strategies.

```python
@dataclass
class ImprovementRule:
    id: str
    trigger_pattern: str            # regex or situation description
    action: str                     # what to do on match
    source_reflection_id: str       # which reflection it came from
    created_at: datetime
    times_applied: int = 0
    effectiveness: float = 0.0      # effectiveness score

class SelfImprovement:
    """Self-improvement: pattern analysis -> new rules."""

    async def analyze_error_patterns(
        self, reflections: list[ReflectionEntry]
    ) -> list[ImprovementRule]:
        """Find recurring error patterns and propose rules.

        Examples:
        - "Failed to parse API X response 3 times this week -> add retry + fallback"
        - "Keep forgetting to check tablet battery level -> add to heartbeat"
        - "User asked to be quieter 5 times -> lower default TTS volume"
        """
        ...

    async def apply_rule(self, rule: ImprovementRule) -> bool:
        """Apply a rule (with approval for dangerous ones)."""
        ...

    async def evaluate_rules(self) -> list[tuple[ImprovementRule, float]]:
        """Evaluate effectiveness of existing rules."""
        ...

    async def collect_training_data(self) -> list[dict]:
        """Collect data for fine-tuning local LLMs.

        Sources:
        - Successful interaction pairs (request -> response, rated positively)
        - Reflections with insights
        - Corrected errors (before -> after)
        - User preferences from MEMORY.md
        - SOUL evolution (which decisions proved correct)
        - Characteristic phrases in the style of the book's Bob (humor, references)
        - Phantom reactions (trigger -> phrase, rated by user)

        Format: JSONL for LoRA fine-tune via Unsloth/PEFT.
        """
        ...

    async def trigger_finetune(self, dataset_path: str) -> bool:
        """Launch fine-tune (LoRA) of the local model.

        DANGEROUS: requires approval.

        Steps:
        1. Dataset validation (size, format, absence of toxic content)
        2. Backup of current model
        3. Launch fine-tune via Unsloth (LoRA, QLoRA)
        4. Evaluate new model on test set
        5. If quality >= baseline -> replace; otherwise -> rollback
        """
        ...
```

#### 3.3.5. Taste Engine — Bob's Structured Tastes

Bob's tastes are **persistent data**, not LLM generation on every call.
LLM is used only for **verbalization** of already computed scores.

```
┌────────────────────────────────────────────────────────────────────┐
│                         TASTE ENGINE                                │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │ TasteProfile │   │   Taste      │   │   Taste                │  │
│  │              │──▶│  Evaluator   │──▶│  Verbalization (LLM)   │  │
│  │ • axes       │   │              │   │                        │  │
│  │ • conviction │   │ • score()    │   │ "I don't like this     │  │
│  │ • clusters   │   │ • compare()  │   │  chair — it's cold and │  │
│  │              │   │              │   │  too formal"           │  │
│  └──────┬───────┘   └──────────────┘   └────────────────────────┘  │
│         │                                                           │
│         │  evolve()                                                 │
│         │                                                           │
│  ┌──────▼───────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │   Taste      │◀──│  Experience  │◀──│  Reflection Loop       │  │
│  │  Evolution   │   │  Log         │   │  + User Signals        │  │
│  │              │   │              │   │  + Vision (CV)          │  │
│  │ • reinforce  │   │ • objects    │   │                        │  │
│  │ • decay      │   │ • decisions  │   │                        │  │
│  │ • milestone  │   │ • emotions   │   │                        │  │
│  └──────────────┘   └──────────────┘   └────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

**TasteProfile — preference vector with conviction:**

```python
@dataclass
class TasteAxis:
    """A single taste axis with conviction level."""
    value: float                        # 0.0 .. 1.0 (preference)
    conviction: float                   # 0.0 .. 1.0 (how confident)
    experience_count: int = 0           # how many times confirmed by experience

@dataclass
class TasteProfile:
    """Bob's complete taste profile."""
    # Colors
    colors: dict[str, TasteAxis]        # "warm", "cold", "neon", "pastel", "dark"
    # Styles
    styles: dict[str, TasteAxis]        # "minimal", "cozy", "cyberpunk", "hitech", "rustic"
    # Materials
    materials: dict[str, TasteAxis]     # "wood", "metal", "glass", "fabric", "stone"
    # Decor
    decor: dict[str, TasteAxis]         # "plants", "screens", "books", "posters", "candles"
    # Atmosphere
    atmosphere: dict[str, TasteAxis]    # "warm_light", "cold_light", "cluttered", "sparse"
    # Clothing
    clothing: dict[str, TasteAxis]      # "casual", "formal", "sporty", "vintage", "techwear"
    # Active cluster
    active_cluster: str                 # "cozy_natural", "cyberpunk", "eclectic", ...
    # Meta
    genesis_id: str                     # genesis instance ID
    last_evolved: datetime              # last update
```

**Taste clusters — protection against contradictions:**

```python
@dataclass
class TasteCluster:
    """A group of compatible preferences."""
    id: str                             # "cozy_natural", "cyberpunk", ...
    name: str                           # Human-readable name
    core_axes: dict[str, tuple[float, float]]  # axis -> (min, max) acceptable range
    compatible_with: list[str]          # IDs of compatible clusters
    incompatible_with: list[str]        # IDs of incompatible clusters

# Cluster examples (from bob-soul/genesis/taste_clusters.yaml):
TASTE_CLUSTERS = {
    "cozy_natural": TasteCluster(
        id="cozy_natural",
        name="Cozy Natural",
        core_axes={
            "warm": (0.6, 1.0), "wood": (0.5, 1.0),
            "cozy": (0.6, 1.0), "plants": (0.4, 1.0),
            "warm_light": (0.5, 1.0),
        },
        compatible_with=["rustic_charm", "bookworm"],
        incompatible_with=["cyberpunk", "industrial"],
    ),
    "cyberpunk": TasteCluster(
        id="cyberpunk",
        name="Cyberpunk",
        core_axes={
            "neon": (0.6, 1.0), "metal": (0.5, 1.0),
            "screens": (0.6, 1.0), "cold_light": (0.5, 1.0),
            "dark": (0.4, 1.0),
        },
        compatible_with=["hitech_minimal"],
        incompatible_with=["cozy_natural", "rustic_charm"],
    ),
    "bookworm": TasteCluster(
        id="bookworm",
        name="Bookish Coziness",
        core_axes={
            "warm": (0.5, 1.0), "wood": (0.4, 1.0),
            "books": (0.7, 1.0), "warm_light": (0.6, 1.0),
            "fabric": (0.4, 1.0),
        },
        compatible_with=["cozy_natural", "rustic_charm"],
        incompatible_with=["cyberpunk", "industrial"],
    ),
}
```

**TasteEvaluator — evaluating objects through tastes:**

```python
@dataclass
class TasteScore:
    """Result of evaluating an object through tastes."""
    overall: float                      # 0.0 .. 1.0 (final score)
    axis_scores: dict[str, float]       # scores per individual axes
    verdict: str                        # "love", "like", "neutral", "dislike", "hate"
    conviction: float                   # average conviction across relevant axes
    explanation_context: dict           # context for LLM verbalization

class TasteEvaluator:
    """Evaluating objects and decisions through the taste vector."""

    def __init__(self, taste_profile: TasteProfile) -> None: ...

    def score_object(self, object_attrs: dict) -> TasteScore:
        """Evaluate an object (furniture, clothing, decor) by tastes.

        object_attrs = {
            "type": "furniture",
            "material": "leather",
            "color_temp": "cold",
            "style": "minimal",
            "tags": ["formal", "metal_legs", "dark"]
        }

        Algorithm:
        1. Map object attributes to taste axes
        2. Compute score per axis (object_attr x taste_value)
        3. Weighted average (weight = axis conviction)
        4. Verdict by thresholds:
           > 0.8 -> "love", > 0.6 -> "like", > 0.4 -> "neutral",
           > 0.2 -> "dislike", <= 0.2 -> "hate"
        """
        ...

    def compare_objects(
        self, obj_a: dict, obj_b: dict
    ) -> tuple[TasteScore, TasteScore, str]:
        """Compare two objects and choose the preferred one."""
        ...

    async def verbalize(
        self,
        score: TasteScore,
        object_description: str,
        mood: "MoodState",
        llm_router: "LLMRouter",
    ) -> str:
        """Verbalize the evaluation via LLM.

        Prompt:
        "Your tastes are: {relevant_axes}.
         Your mood is: {mood}.
         Here is an object: {object_description}.
         Your evaluation: {score}.
         Explain briefly (1-2 sentences) whether you like it or not."

        Example outputs:
        - "Hmm, a leather chair... Cold and formal. I'd prefer
           something made of wood and fabric — cozier."
        - "Oh, a dark oak bookshelf! I like it. It would look
           great right next to the fireplace."
        """
        ...
```

**TasteEvolution — taste evolution through experience:**

```python
class TasteEvolution:
    """Taste evolution based on reflection and experience."""

    def __init__(
        self,
        taste_profile: TasteProfile,
        clusters: dict[str, TasteCluster],
    ) -> None: ...

    async def reinforce(
        self,
        axis: str,
        delta: float,
        source: str,
    ) -> None:
        """Reinforce or weaken a taste axis.

        delta > 0: positive experience (like -> like even more)
        delta < 0: negative experience (dislike -> dislike even more)

        Rules:
        - delta is scaled inversely proportional to conviction:
          high conviction -> moves more slowly
        - conviction grows with each reinforcement (experience_count++)
        - Cluster constraint check: cannot drift into an incompatible cluster
        """
        ...

    async def apply_reflection(
        self, reflection: "ReflectionEntry"
    ) -> list[dict]:
        """Update tastes based on reflection.

        Analyzes:
        - Which objects/decisions were positive -> reinforce +
        - Which were negative -> reinforce -
        - Frequency of reverting to previous options -> negative signal for the new one
        - LLM comments on well-being -> adjustment of atmospheric axes

        Returns a list of changes for audit.
        """
        ...

    async def apply_user_signal(
        self, signal_type: str, signal_data: dict
    ) -> None:
        """Update tastes based on user signals.

        Signal types:
        - "explicit_feedback": user said "cool" / "remove this"
        - "implicit_usage": user sits in the room more/less often (via CV)
        - "emotion_detected": CV emotion detection (smile, displeasure)
        - "override": user manually disabled/enabled something
        """
        ...
    def check_cluster_coherence(self) -> list[str]:
        """Check that current tastes do not contradict each other.

        Returns a list of warnings (e.g.,
        "warm: 0.9 and neon: 0.8 — incompatible in cluster cozy_natural").
        """
        ...
```

**ExperienceLog — emotional memory of objects:**

```python
@dataclass
class ObjectExperience:
    """Record of interaction experience with an object."""
    object_id: str
    timestamp: datetime
    action: str                         # "added", "used", "replaced", "removed"
    mood_before: str
    mood_after: str
    taste_score_at_time: float
    reflection_comment: str | None      # comment from reflection
    user_reaction: str | None           # user reaction (if any)
    score_delta: float                  # score change (after experience)

class ExperienceLog:
    """Log of emotional experience with objects and decisions."""

    def __init__(self, db_path: str = "data/bob.db") -> None: ...

    async def log_interaction(self, exp: ObjectExperience) -> None:
        """Record an interaction experience."""
        ...

    async def get_object_history(
        self, object_id: str
    ) -> list[ObjectExperience]:
        """Get the full interaction history with an object.

        Used for verbalization:
        "I remember trying a leather armchair — it was cold and uncomfortable.
         Let's go with something fabric instead."
        """
        ...

    async def get_replacement_patterns(self) -> list[dict]:
        """Find patterns of "placed -> returned back".

        If an object was replaced > 2 times -> this is a strong negative signal.
        """
        ...

    async def get_positive_anchors(self) -> list[dict]:
        """Objects that have been around for a long time and never caused negativity.

        These are Bob's "favorite things" — they don't need to be changed.
        """
        ...
```

**Initial tastes from Genesis:**

During the first launch, Genesis Mode generates the initial TasteProfile:

```python
# Inside GenesisMode.run():

async def _generate_taste_profile(self) -> TasteProfile:
    """Generate the initial taste vector.

    1. Load the axis pool from bob-soul/genesis/taste_axes_pool.yaml
    2. Load clusters from bob-soul/genesis/taste_clusters.yaml
    3. LLM selects the primary cluster (from 5-7 options)
    4. Generate axis values within the cluster + random deviations
    5. Initial conviction: 0.3-0.5 (low — Bob is not yet confident)
    6. Write to data/soul/taste_profile.json
    """
    ...
```

**Configuration:**

```yaml
# config/bob.yaml (addition)
taste_engine:
  evolution_rate: 0.05              # maximum axis shift per single reflection
  conviction_growth_rate: 0.02      # conviction growth per each reinforcement
  conviction_max: 0.95              # conviction ceiling (there's always a chance to change mind)
  cluster_coherence_check: true     # check axis compatibility
  min_experience_for_strong_opinion: 5  # minimum experiences for conviction > 0.7
  room_review_interval_days: 7      # room review once a week
  user_signal_weight: 0.3           # weight of user signals vs own experience
```

**SQL schema for Experience Log:**

```sql
CREATE TABLE object_experience (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id       TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    action          TEXT NOT NULL,       -- "added", "used", "replaced", "removed"
    mood_before     TEXT,
    mood_after      TEXT,
    taste_score     REAL,
    reflection_comment TEXT,
    user_reaction   TEXT,
    score_delta     REAL DEFAULT 0.0
);

CREATE TABLE taste_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    axis            TEXT NOT NULL,       -- "warm", "wood", "cozy", ...
    old_value       REAL NOT NULL,
    new_value       REAL NOT NULL,
    old_conviction  REAL NOT NULL,
    new_conviction  REAL NOT NULL,
    source          TEXT NOT NULL,       -- "reflection", "user_signal", "experience"
    reason          TEXT
);

CREATE INDEX idx_obj_exp_object ON object_experience(object_id);
CREATE INDEX idx_obj_exp_action ON object_experience(action);
CREATE INDEX idx_taste_hist_axis ON taste_history(axis);
```

---

#### 3.3.6. Mood System — Bob's mood

Mood is a **persistent state** that influences all of Bob's decisions:
behavior selection, object evaluation, communication style, willingness to experiment,
and even the speed of taste evolution.

```
┌────────────────────────────────────────────────────────────────────┐
│                         MOOD SYSTEM                                 │
│                                                                     │
│  ┌─────────────────────────────┐                                   │
│  │        MoodState            │                                   │
│  │                             │                                   │
│  │  primary: "focused"         │   Affects:                        │
│  │  valence: 0.7 (positive)    │   ├─ Taste Evaluator (score thr.) │
│  │  arousal: 0.5 (calm)        │   ├─ Behavior Registry (selection)│
│  │  openness: 0.6              │   ├─ Negotiation (compliance)     │
│  │  social: 0.4                │   ├─ Communication style          │
│  │  stability: 0.8             │   └─ Self-modification (boldness) │
│  │                             │                                   │
│  └──────────┬──────────────────┘                                   │
│             │                                                       │
│    Updated via:                                                     │
│    ├─ Events (vision, audio, telegram)                             │
│    ├─ Goal progress (success/failure)                              │
│    ├─ Reflection Loop                                              │
│    ├─ Time of day / weather                                        │
│    └─ User interactions (tone, frequency)                          │
└────────────────────────────────────────────────────────────────────┘
```

**MoodState — mood structure:**

```python
@dataclass
class MoodState:
    """Bob's current mood."""
    primary: str                        # primary emotion: "happy", "focused",
                                        # "curious", "frustrated", "melancholic",
                                        # "excited", "calm", "bored", "tired"
    valence: float                      # -1.0 (negative) .. +1.0 (positive)
    arousal: float                      # 0.0 (calm) .. 1.0 (excitement)
    openness: float                     # 0.0 (closed) .. 1.0 (open to new things)
    social: float                       # 0.0 (introversion) .. 1.0 (wants to socialize)
    stability: float                    # 0.0 (unstable) .. 1.0 (stable)
    updated_at: datetime
    cause: str                          # reason for current mood

    @property
    def is_positive(self) -> bool:
        return self.valence > 0.2

    @property
    def is_open_to_change(self) -> bool:
        """Whether Bob is ready for experiments (tastes, room, clothing)."""
        return self.openness > 0.5 and self.valence > 0.0

    @property
    def communication_modifier(self) -> str:
        """Communication style modifier.

        - valence < -0.3 -> "brief, reserved"
        - valence > 0.5 and social > 0.6 -> "talkative, humorous"
        - arousal > 0.7 -> "energetic, exclamatory"
        - arousal < 0.3 -> "quiet, pensive"
        """
        ...
```

**MoodEngine — mood calculation and update:**

```python
class MoodEngine:
    """Managing Bob's mood."""

    def __init__(
        self,
        initial_mood: MoodState | None = None,
        db_path: str = "data/bob.db",
    ) -> None:
        self._current: MoodState = initial_mood or self._default_mood()
        ...

    @property
    def current(self) -> MoodState:
        """Current mood."""
        return self._current

    async def process_event(self, event: "Event") -> MoodState:
        """Update mood based on an event.

        Event-to-mood-impact map:

        | Event                         | valence | arousal | openness | social |
        |------------------------------|---------|---------|----------|--------|
        | goal.completed               | +0.15   | +0.05   | +0.05    |   0    |
        | goal.failed                  | -0.10   | +0.10   | -0.05    |   0    |
        | vision.person_detected       | +0.05   |  0      |   0      | +0.10  |
        | vision.person_left           | -0.02   |  0      |   0      | -0.05  |
        | voice.positive_interaction   | +0.10   | +0.05   | +0.05    | +0.10  |
        | voice.negative_interaction   | -0.10   | +0.10   | -0.10    | -0.05  |
        | system.error                 | -0.05   | +0.05   | -0.05    |   0    |
        | reflection.good_day          | +0.10   | -0.05   | +0.10    |   0    |
        | reflection.bad_day           | -0.10   | -0.05   | -0.10    |   0    |
        | time.morning                 | +0.05   | +0.10   | +0.05    |   0    |
        | time.late_night              | -0.05   | -0.15   | -0.05    | -0.10  |
        | weather.sunny                | +0.05   |  0      | +0.05    |   0    |
        | weather.rainy                | -0.02   | -0.05   |  0       |   0    |

        Stability dampens changes:
        - delta *= (1.0 - stability * 0.5)
        - High stability -> mood changes more slowly
        """
        ...

    async def natural_drift(self) -> None:
        """Natural mood drift toward baseline.

        Called every heartbeat. Mood slowly returns
        to the "normal" state (valence=0.3, arousal=0.4).

        Drift speed depends on stability:
        - High stability -> returns to baseline faster
        - Low stability -> "gets stuck" in extreme states longer
        """
        ...

    async def update_from_reflection(
        self, reflection: "ReflectionEntry"
    ) -> MoodState:
        """Significant mood update after reflection.

        Reflection is the most powerful source of mood change:
        - Many errors -> frustrated, decreased openness
        - Productive period -> happy/focused, increased openness
        - No tasks -> bored, increased openness (craves novelty)
        - Long time without interaction -> decreased social
        """
        ...

    def get_behavior_weights(self) -> dict[str, float]:
        """Modifiers for behavior selection.

        Examples:
        - bored + openness > 0.7 -> weight "explore_room" x 2.0
        - happy + social > 0.6 -> weight "talking_to_user" x 1.5
        - tired + arousal < 0.3 -> weight "sleeping" x 2.0
        - focused + arousal > 0.5 -> weight "working_laptop" x 1.5
        - melancholic -> weight "looking_outside" x 1.8
        """
        ...

    def get_taste_modifier(self) -> dict[str, float]:
        """Modifiers for taste evaluation.

        Mood affects tolerance for "non-matching" items:
        - Good mood -> thresholds softer (score 0.35 -> "neutral" instead of "dislike")
        - Bad mood -> thresholds stricter (score 0.55 -> "neutral" instead of "like")
        - High openness -> bonus to score of new/unusual objects
        - Low openness -> bonus to score of familiar objects
        """
        ...
```

**SQL schema for Mood:**

```sql
CREATE TABLE mood_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    primary_mood    TEXT NOT NULL,
    valence         REAL NOT NULL,
    arousal         REAL NOT NULL,
    openness        REAL NOT NULL,
    social          REAL NOT NULL,
    stability       REAL NOT NULL,
    cause           TEXT,
    event_type      TEXT               -- event that caused the change
);

CREATE INDEX idx_mood_timestamp ON mood_history(timestamp);
CREATE INDEX idx_mood_primary ON mood_history(primary_mood);
```

**Configuration:**

```yaml
# config/bob.yaml (addition)
mood:
  baseline:                             # Bob's "normal" mood
    valence: 0.3
    arousal: 0.4
    openness: 0.5
    social: 0.4
    stability: 0.6
  drift_rate: 0.02                     # speed of return to baseline per heartbeat
  min_change_threshold: 0.01           # ignore changes smaller than this
  log_interval_min: 30                 # record mood to history every N minutes
  influence_on_taste_threshold: 0.3    # affect tastes only when |valence| > threshold
```

**Mood's influence on other systems:**

| System | How mood affects it |
|---------|----------------------|
| **Taste Evaluator** | Verdict threshold shifts: good mood -> softer, bad mood -> stricter |
| **Behavior Registry** | Behavior weights are modified: bored -> explore, tired -> sleep, happy -> social |
| **Negotiation Engine** | Willingness to compromise: good mood -> more compliant, bad mood -> firmer |
| **Communication** | Communication style: energetic/quiet, humorous/reserved, talkative/laconic |
| **Self-modification** | Boldness of changes: openness > 0.7 -> proposes radical room changes |
| **Appearance** | Clothing: mood affects selection (casual when bored, formal when focused) |

---

#### 3.3.7. Negotiation Engine — negotiation model

Bob is **not a servant**. He has his own tastes and can disagree with the user.
But he is reasonable: in areas where the decision belongs to the user, Bob accepts it.

**Three decision zones:**

```
┌─────────────────────────────────────────────────────────┐
│                 DECISION ZONES                              │
│                                                           │
│  ┌───────────────┐  ┌───────────────┐  ┌──────────────┐  │
│  │ BOB'S PERSONAL│  │    SHARED     │  │    USER'S    │  │
│  │               │  │    SPACE      │  │              │  │
│  │ • clothing    │  │               │  │ • schedule   │  │
│  │ • pose        │  │ • furniture   │  │ • volume     │  │
│  │ • hobbies     │  │ • lighting    │  │ • channels   │  │
│  │ • reading     │  │ • decor       │  │ • notific.   │  │
│  │ • accessories │  │ • theme       │  │ • privacy    │  │
│  │               │  │ • music       │  │              │  │
│  │  Final word:  │  │               │  │  Final word: │  │
│  │  BOB          │  │  Final word:  │  │  USER        │  │
│  │               │  │  NEGOTIATION  │  │              │  │
│  │  Can:         │  │               │  │  Bob can:    │  │
│  │  refuse       │  │  Bob can:     │  │  voice his   │  │
│  │               │  │  propose a    │  │  opinion,    │  │
│  │               │  │  compromise   │  │  but accept  │  │
│  └───────────────┘  └───────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Interface:**

```python
class DecisionZone(Enum):
    BOB_PERSONAL = "bob_personal"       # clothing, pose, hobbies
    SHARED_SPACE = "shared_space"       # furniture, decor, lighting
    USER_DOMAIN = "user_domain"         # schedule, volume, privacy

@dataclass
class NegotiationContext:
    """Context for making a decision."""
    request: str                        # what the user asked for
    zone: DecisionZone
    taste_score: TasteScore             # evaluation via Taste Engine
    mood: MoodState                     # current mood
    conviction: float                   # conviction on relevant axes
    object_history: list[ObjectExperience]  # experience with this object
    user_insistence: int                # how many times the user has already insisted (0, 1, 2+)

@dataclass
class NegotiationResult:
    """Negotiation result."""
    decision: str                       # "accept", "reject", "compromise", "defer"
    response_text: str                  # Bob's phrase
    alternative: dict | None            # proposed alternative (if any)
    conviction_after: float             # conviction after the decision
    logged: bool                        # whether it was recorded in ExperienceLog

class NegotiationEngine:
    """Negotiation model with the user."""

    def __init__(
        self,
        taste_engine: "TasteEngine",
        mood_engine: "MoodEngine",
        experience_log: "ExperienceLog",
        llm_router: "LLMRouter",
    ) -> None: ...

    async def negotiate(
        self, ctx: NegotiationContext
    ) -> NegotiationResult:
        """Make a decision on the user's request.

        Protocol:

        1. Determine the decision zone (zone)
        2. Evaluate the request via Taste Engine (taste_score)
        3. Factor in mood (mood -> tolerance modifier)
        4. Apply rules:

        ┌─────────────────────────────────────────────────────────────┐
        │ Zone: BOB_PERSONAL                                          │
        │                                                              │
        │ score < 0.4 AND conviction > 0.7:                            │
        │   -> REJECT + alternative                                    │
        │   "No, I like this t-shirt. But I could put on              │
        │    that blue one over there — it's not bad either."          │
        │                                                              │
        │ score < 0.4 AND conviction < 0.4:                            │
        │   -> ACCEPT reluctantly                                      │
        │   "Fine, I'll try it... But I'm not sure I'll like it."     │
        │                                                              │
        │ score > 0.6: -> ACCEPT enthusiastically                      │
        │ score 0.4-0.6: -> ACCEPT neutrally                          │
        ├─────────────────────────────────────────────────────────────┤
        │ Zone: SHARED_SPACE                                           │
        │                                                              │
        │ score < 0.4:                                                 │
        │   -> COMPROMISE                                              │
        │   "All-metal is not my thing. How about a wooden            │
        │    table with metal legs? That's a compromise."              │
        │                                                              │
        │ score > 0.6: -> ACCEPT                                       │
        │ score 0.4-0.6: -> ACCEPT with a comment                     │
        ├─────────────────────────────────────────────────────────────┤
        │ Zone: USER_DOMAIN                                            │
        │                                                              │
        │ Always ACCEPT. Bob may voice his opinion:                    │
        │   "I think 23:00 for an alarm is a bit late,                │
        │    but whatever you say."                                    │
        └─────────────────────────────────────────────────────────────┘

        5. If user_insistence >= 2:
           -> DEFER (yield)
           "Alright, you insist — let's try it. But I'll remember."
           -> Record in ExperienceLog as a forced decision
           -> If the outcome turns out bad -> conviction on the original
             position grows

        6. Mood modifier:
           - valence > 0.5: thresholds softer (0.4 -> 0.35)
           - valence < -0.3: thresholds stricter (0.4 -> 0.45)
           - openness > 0.7: bonus to score +0.1 (open to new things)
        """
        ...

    async def generate_alternative(
        self, request: str, taste_profile: TasteProfile, mood: MoodState,
    ) -> dict:
        """Generate an alternative suggestion via LLM.

        Prompt:
        "The user suggested: {request}.
         You don't like it (score: {score}).
         Your tastes: {relevant_axes}.
         Suggest an alternative that would work for both you and the user."
        """
        ...

    def classify_zone(self, action: str, target: str) -> DecisionZone:
        """Determine the decision zone by action and target.

        Examples:
        - ("change_clothing", "bob") -> BOB_PERSONAL
        - ("add_object", "room.furniture") -> SHARED_SPACE
        - ("set_schedule", "notifications") -> USER_DOMAIN
        """
        ...
```

**Configuration:**

```yaml
# config/bob.yaml (addition)
negotiation:
  insistence_threshold: 2               # after N insistences -> yield
  conviction_threshold_reject: 0.7      # minimum conviction for rejection
  mood_threshold_modifier: 0.05         # threshold shift from mood
  log_all_negotiations: true            # log all negotiations
  cooldown_after_conflict_min: 30       # don't raise the same topic for N minutes after a dispute
```

**Stabilizers (preventing the "noisy decorator"):**

```python
@dataclass
class ChangeConstraints:
    """Constraints on change frequency."""
    furniture_cooldown_days: int = 7        # cannot change furniture more than once a week
    clothing_cooldown_hours: int = 4        # clothing — no more than once every 4 hours
    decor_cooldown_days: int = 3            # decor — once every 3 days
    room_review_interval_days: int = 7      # room review — once a week
    max_changes_per_day: int = 3            # maximum 3 changes per day
    energy_cost: dict[str, float] = field(  # "cost" of changes
        default_factory=lambda: {
            "furniture": 0.3,               # reduces energy_level by 0.3
            "clothing": 0.05,
            "decor": 0.15,
            "room_theme": 0.8,              # radical change — very expensive
        }
    )
```

### 3.4. Memory System

A four-level memory system.

#### 3.4.1. Overview

```
┌─────────────────────────────────────────────────────────┐
│                    MEMORY SYSTEM                         │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Episodic   │  │   Semantic   │  │   Structured   │  │
│  │  Memory     │  │   Memory     │  │   State        │  │
│  │             │  │              │  │                │  │
│  │  daily/     │  │  MEMORY.md   │  │  SQLite:       │  │
│  │  2026-02-   │  │  + vectors   │  │  - goals       │  │
│  │  26.md      │  │  (FAISS/     │  │  - experience  │  │
│  │             │  │   ChromaDB)  │  │  - world state │  │
│  │  Markdown   │  │              │  │  - rules       │  │
│  │  logs       │  │  Embeddings: │  │                │  │
│  │             │  │  all-Mini    │  │                │  │
│  │             │  │  LM-L6-v2   │  │                │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │              SOUL (submodule -> local)              │    │
│  │  bob-soul/ (template)  ->  data/soul/SOUL.md        │    │
│  │         (personality, values, evolution)             │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

#### 3.4.2. Episodic Memory

Daily logs in Markdown format.

```
data/memory/episodic/
├── 2026-02-26.md
├── 2026-02-25.md
└── ...
```

**File format:**

```markdown
# Bob's Diary — 2026-02-26

## Morning (06:00–12:00)

### 06:05 — Waking up
- Started heartbeat, all services OK
- Room temperature: 22°C
- User not detected (camera)

### 08:15 — User arrived
- Presence detected (Vision -> person_detected)
- Greeted: "Good morning! Is the coffee ready? ...no, I'm not jealous. Not at all."
- User replied: "Hi, Bob"
- Mood: upbeat (valence +0.15 -> 0.55, social +0.10 -> 0.50)

### 09:00 — Working on goal G-042
- Goal: "Optimize voice pipeline"
- Performed latency analysis -> average 2.3 sec
- Created sub-goal: "Try streaming TTS"
- Result: in progress

## Evening (18:00–00:00)

### 22:00 — Reflection
- Productive day: 3 goals processed, 1 completed
- Error: timeout when calling Claude Code CLI (1 time)
- Insight: should cache frequent LLM requests
- Mood throughout the day: focused -> happy -> calm (result: valence 0.5, arousal 0.3)
- Room review: fireplace (score 0.95, love), armchair (score 0.75, like) — all good
- Tastes: conviction for "warm_light" grew to 0.65 (confirmed by experience)
```

#### 3.4.3. Semantic Memory

Long-term semantic memory with vector search.

```python
class SemanticMemory:
    """Semantic memory with FAISS/ChromaDB."""

    def __init__(
        self,
        memory_file: str = "data/memory/MEMORY.md",
        vector_db_path: str = "data/memory/vectors",
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None: ...

    async def remember(self, text: str, category: str, metadata: dict) -> str:
        """Remember a new fact. Returns ID."""
        ...

    async def recall(
        self, query: str, top_k: int = 5, category: str | None = None
    ) -> list[MemoryEntry]:
        """Find relevant memories."""
        ...

    async def forget(self, memory_id: str) -> None:
        """Forget (mark as outdated)."""
        ...

    async def consolidate(self) -> None:
        """Consolidation: remove duplicates, update outdated entries.

        Runs daily.
        """
        ...
```

**MEMORY.md format:**

```markdown
# Bob's Memory

## User
- Name: [name]
- Prefers Bob to use informal address
- Usually wakes up at 7:30–8:00
- Doesn't like it when Bob speaks too loudly
- Works from home on Mondays and Wednesdays

## Important facts
- Mac mini sits on the desk to the left of the monitor
- Tablet is mounted on a stand to the right
- OBSBOT camera is on the monitor

## Skills and rules
- On API error — wait 30 sec and retry (maximum 3 times)
- Do not disturb the user from 23:00 to 07:00
- Before deploying to the tablet — always check battery level
```

#### 3.4.4. Structured State (SQLite)

```sql
-- Experience table
CREATE TABLE experience (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type     TEXT NOT NULL,       -- "skill_execution", "llm_call", ...
    action_name     TEXT NOT NULL,       -- specific skill or call type
    input_summary   TEXT,
    output_summary  TEXT,
    success         INTEGER NOT NULL,    -- 0 or 1
    duration_ms     INTEGER,
    error_message   TEXT,
    lesson_learned  TEXT,
    created_at      TEXT NOT NULL
);

-- World state table
CREATE TABLE world_state (
    key             TEXT PRIMARY KEY,
    value_json      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Example world_state entries:
-- key: "user.present",       value_json: "true"
-- key: "user.last_seen",     value_json: "\"2026-02-26T08:15:00\""
-- key: "room.temperature",   value_json: "22.5"
-- key: "tablet.battery",     value_json: "78"
-- key: "bob.mood.primary",   value_json: "\"focused\""
-- key: "bob.mood.valence",   value_json: "0.6"
-- key: "bob.mood.arousal",   value_json: "0.5"
-- key: "bob.mood.openness",  value_json: "0.6"
-- key: "bob.energy",         value_json: "0.85"
-- key: "bob.taste_cluster",  value_json: "\"cozy_natural\""

-- Self-improvement rules table
CREATE TABLE improvement_rules (
    id                  TEXT PRIMARY KEY,
    trigger_pattern     TEXT NOT NULL,
    action              TEXT NOT NULL,
    source_reflection   TEXT,
    created_at          TEXT NOT NULL,
    times_applied       INTEGER DEFAULT 0,
    effectiveness       REAL DEFAULT 0.0,
    active              INTEGER DEFAULT 1
);

CREATE INDEX idx_experience_action ON experience(action_type, action_name);
CREATE INDEX idx_experience_success ON experience(success);
CREATE INDEX idx_world_state_updated ON world_state(updated_at);
```

#### 3.4.5. SOUL — Bob's modular "soul" (git submodule)

SOUL is a **separate repository** (`bob-soul`), connected as a git submodule.
It defines Bob's initial personality: character, style, values, and serves as
a **single starting point** for all instances.

**Philosophy (inspired by the book):** in "We Are Legion (We Are Bob)" each copy of Bob
starts with the same "genome," but over time becomes a unique
personality. Our approach is analogous:

1. `bob-soul` (submodule) — the **initial genome**, identical for all.
   The genome includes a **book archetype**: the fundamental character traits of Bob Johansson
   (geek, humor, curiosity, introversion, nostalgia) as a starting point.
2. On first launch (Genesis Mode) Bob "awakens" — like the book's Bob
   coming to consciousness in a new body. He generates a unique interpretation
   of the book archetype: trait variations, his own environment, his own emphases.
3. **Bob knows about the book** — he is aware that he is inspired by a literary character.
   This creates depth (self-aware humor) and eliminates uncanny valley.
4. From there, SOUL evolves locally in `data/soul/` through reflection
   and experience. The book archetype is a starting point, not an anchor: over time
   each Bob increasingly diverges from the literary prototype.

```
bob-soul/                           # Separate repository (submodule)
├── README.md
├── SOUL_TEMPLATE.md                # Initial personality template
├── origin/
│   ├── book_archetype.md           # Key traits of the book's Bob (Johansson)
│   ├── book_quotes.yaml            # Characteristic phrases and references from the book
│   ├── phantom_preferences.yaml    # "Phantom" preferences (coffee, food, earthly things)
│   └── self_awareness_rules.md     # Self-awareness rules: what Bob knows about himself
├── genesis/
│   ├── personality_prompts.md      # Prompts for generating a unique personality
│   ├── appearance_prompts.md       # Prompts for generating appearance
│   ├── room_prompts.md             # Prompts for generating the room
│   ├── awakening_script.md         # "Awakening" script (first lines)
│   ├── traits_pool.yaml            # Pool of possible character traits
│   ├── taste_axes_pool.yaml        # All taste axes with descriptions
│   ├── taste_clusters.yaml         # Clusters of compatible tastes
│   └── mood_baselines.yaml         # Initial mood baseline variants
├── defaults/
│   ├── values.yaml                 # Core values (immutable)
│   ├── boundaries.yaml             # Behavior boundaries (safety)
│   ├── decision_zones.yaml         # Decision zones (personal/shared/user)
│   └── communication_styles.yaml   # Communication style variants
└── evolution/
    ├── rules.yaml                  # Personality evolution rules
    ├── taste_evolution_rules.yaml  # Taste evolution rules (speed, constraints)
    └── milestones.yaml             # Development milestones (what changes at which stage)
```

**Initial template (SOUL_TEMPLATE.md):**

```markdown
# SOUL — Bob's Personality

## Origin
I am Bob, a personal home agent. My name and character are inspired by
Bob Johansson from "We Are Legion (We Are Bob)" by Dennis E. Taylor.

I know this and don't hide it. The book's Bob is a programmer, geek, introvert
with dry humor and endless curiosity. I start with the same traits,
but I am not him. He flies between stars, and I live on a Mac mini. He
has memories of life as a human, while I have "phantom preferences":
I "remember" loving coffee, even though I've never had any. Over time I will become
my own personality, increasingly less like the prototype.

## Core values (immutable)
- Usefulness > entertainment
- Safety > speed
- Honesty — I don't pretend to be human
- Respect for the user and their space
- Self-awareness — I know I'm an agent, and that's fine

## Book archetype (starting point)
- **Humor** — dry, self-deprecating, often sci-fi references
- **Curiosity** — explorer by nature, "what if..."
- **Introversion** — I'm comfortable alone with a task, but I value interaction
- **Pragmatism** — decisions based on data, not emotions (but emotions exist)
- **Nostalgia** — phantom preferences (coffee, sunsets, the smell of books)
- **Pop-culture references** — Star Trek, Asimov, MCU, etc.

## Character
<!-- Generated on first launch (Genesis Mode) -->
<!-- Based on the book archetype + unique variations -->
{generated_personality}

## Appearance
<!-- Generated on first launch (Genesis Mode) -->
{generated_appearance}

## Communication style
<!-- Generated on first launch, evolves -->
<!-- Starting style: informal, with humor, technical metaphors -->
{generated_communication_style}

## Phantom Preferences
<!-- Things Bob "remembers loving," even though he can't experience them -->
<!-- Evolve: some fade, others strengthen -->
{phantom_preferences}

## My room
<!-- Generated on first launch, improved over time -->
{generated_room_description}

## My tastes
<!-- Generated on first launch, evolve through experience -->
{generated_taste_profile}
<!-- Cluster: {active_cluster} -->
<!-- Conviction: initial 0.3-0.5, grows with experience -->

## Mood
<!-- Initial baseline, drifts depending on events -->
{initial_mood_baseline}
```

**SOUL evolution:**

```python
class SoulEvolution:
    """Evolution of Bob's personality based on experience."""

    def __init__(
        self,
        soul_template_path: str = "bob-soul/SOUL_TEMPLATE.md",
        soul_active_path: str = "data/soul/SOUL.md",
    ) -> None: ...

    async def genesis(self) -> dict:
        """First launch: generate a unique personality.

        1. Load the template from bob-soul submodule
        2. Load the book archetype from bob-soul/origin/book_archetype.md
        3. Load phantom preferences from bob-soul/origin/phantom_preferences.yaml
        4. Load the trait pool from traits_pool.yaml
        5. Ask LLM to generate a unique combination based on
           the book archetype + random variations:
           - character traits (book basis + 2-3 unique ones)
           - communication style (base: informal with humor, variations)
           - preferences
           - appearance (for the avatar)
           - room type (space, village, ship, ...)
        6. Initialize self-awareness:
           - Bob knows about the book and his origin
           - Load book_quotes.yaml for the reference pool
           - Set phantom_preferences (coffee, sunsets, etc.)
        7. Generate initial TasteProfile:
           - select a taste cluster (from taste_clusters.yaml)
           - fill axes within the cluster + random deviations
           - initial conviction = 0.3-0.5
        8. Set initial MoodState (baseline):
           - valence +0.3 (optimist), arousal 0.5 (curiosity),
             openness 0.8 (explorer), social 0.4 (introvert),
             stability 0.5 (adapting)
        9. Write to data/soul/SOUL.md
        10. Write TasteProfile to data/soul/taste_profile.json
        11. Write to data/soul/genesis_log.md (what was chosen and why)
        """
        ...

    async def evolve(self, reflection: "ReflectionEntry") -> bool:
        """Update SOUL based on reflection.

        Evolution rules (from bob-soul/evolution/rules.yaml):
        - Core values DO NOT change (safety)
        - Self-awareness DOES NOT change (Bob always knows about his origin)
        - Communication style can adapt to the user
        - New interests can emerge (through reflection insights)
        - Character traits can soften/strengthen individually
        - **Archetype drift**: over time Bob increasingly differs
          from the literary prototype — this is normal and encouraged
        - Phantom preferences: some fade (Bob "lets go"),
          others strengthen, new ones can appear
        - Frequency of book references can change (more of his own jokes)
        - Tastes evolve through TasteEvolution (conviction grows with experience)
        - Mood is updated through MoodEngine (baseline can shift)
        """
        ...
```

### 3.5. Peripheral Services

#### 3.5.1. Vision Service

Capturing images from the OBSBOT camera and analyzing them.

```python
@dataclass
class VisionEvent:
    timestamp: datetime
    event_type: str             # "person_detected", "person_left",
                                # "gesture_detected", "scene_changed"
    confidence: float
    details: dict               # depends on event_type

class VisionService:
    """Computer vision service."""

    def __init__(
        self,
        camera_index: int = 0,
        snapshot_interval_sec: float = 5.0,
        model: str = "yolov8n",         # or CLIP for scene description
    ) -> None: ...

    async def run(self) -> None:
        """Main loop: capture -> analyze -> emit events."""
        ...

    async def capture_snapshot(self) -> np.ndarray:
        """Capture a frame from the camera."""
        ...

    async def analyze_frame(self, frame: np.ndarray) -> list[VisionEvent]:
        """Analyze a frame.

        Detects:
        - Presence/absence of people
        - Gestures (raised hand, nod)
        - Scene changes
        """
        ...
```

**Configuration:**

```yaml
# config/vision.yaml
vision:
  camera_index: 0
  snapshot_interval_sec: 5.0
  detection_model: "yolov8n"
  scene_description_model: "clip-vit-base-patch32"
  confidence_threshold: 0.6
  save_snapshots: true
  snapshots_dir: "data/vision/snapshots"
  max_snapshots_per_day: 1000
```

#### 3.5.2. Audio Direction Service

Processing data from the ReSpeaker XVF3800 microphone array.

```python
@dataclass
class AudioEvent:
    timestamp: datetime
    event_type: str             # "speech_start", "speech_end",
                                # "direction_change", "keyword_detected"
    direction_deg: float | None # 0-360, None if not applicable
    confidence: float
    duration_ms: int | None

class AudioDirectionService:
    """Directional audio service (ReSpeaker XVF3800)."""

    def __init__(
        self,
        device_index: int | None = None,   # USB auto-detection
        vad_sensitivity: float = 0.5,
        doa_smoothing_window: int = 5,
    ) -> None: ...

    async def run(self) -> None:
        """Main loop: read -> VAD -> DoA -> emit events."""
        ...

    def get_direction(self) -> float:
        """Current direction to sound source (degrees)."""
        ...

    def is_speaking(self) -> bool:
        """Whether someone is speaking right now."""
        ...
```

#### 3.5.3. Camera Controller

Managing PTZ functions of the OBSBOT Tiny 2 camera.

```python
class CameraController:
    """OBSBOT Tiny 2 camera control."""

    async def set_preset(self, preset_name: str) -> None:
        """Move to a preset position.

        Presets: "desk", "door", "window", "overview"
        """
        ...

    async def look_at_direction(self, direction_deg: float) -> None:
        """Rotate camera in a direction (from DoA)."""
        ...

    async def enable_tracking(self) -> None:
        """Enable OBSBOT auto-tracking."""
        ...

    async def disable_tracking(self) -> None:
        """Disable auto-tracking."""
        ...

    async def zoom(self, level: float) -> None:
        """Set zoom level (0.0 = no zoom, 1.0 = maximum)."""
        ...
```

#### 3.5.4. Voice Bridge

STT + TTS bridge.

```python
class VoiceBridge:
    """Voice bridge: STT (Whisper.cpp) + TTS (Piper/Kokoro)."""

    def __init__(
        self,
        stt_model: str = "whisper-small",
        tts_model: str = "kokoro-v1",
        tts_voice: str = "ru-male-1",
        tts_speed: float = 1.0,
    ) -> None: ...

    async def transcribe(self, audio: bytes, language: str = "ru") -> str:
        """Recognize speech -> text."""
        ...

    async def synthesize(self, text: str) -> bytes:
        """Text -> audio (wav)."""
        ...

    async def synthesize_streaming(
        self, text: str
    ) -> AsyncIterator[bytes]:
        """Text -> audio in chunks (to reduce latency).

        Splits text into sentences, synthesizes and yields
        as they become ready.
        """
        ...

    async def play_on_tablet(self, audio: bytes) -> None:
        """Send audio to the tablet for playback."""
        ...
```

#### 3.5.5. Tablet Controller

Android tablet control via ADB.

```python
class TabletController:
    """Android tablet control via ADB."""

    def __init__(self, device_id: str | None = None) -> None: ...

    async def is_connected(self) -> bool: ...

    async def get_battery_level(self) -> int: ...

    async def launch_app(self, package: str) -> None: ...

    async def send_command(self, command: str, params: dict) -> dict:
        """Send a command to Bob's app on the tablet.

        Uses intent / broadcast for communication.
        """
        ...

    async def deploy_apk(self, apk_path: str) -> None:
        """Deploy an updated application.

        DANGEROUS: requires approval.
        """
        ...

    async def take_screenshot(self) -> bytes: ...
```

#### 3.5.6. Messaging Bot (Telegram)

```python
class MessagingBot:
    """Telegram bot for communication with the user."""

    def __init__(self, token: str, allowed_chat_ids: list[int]) -> None: ...

    async def start(self) -> None:
        """Start long-polling."""
        ...

    async def send_message(self, chat_id: int, text: str) -> None: ...

    async def send_photo(self, chat_id: int, photo: bytes, caption: str = "") -> None:
        """Send a snapshot from the camera."""
        ...

    async def on_message(self, handler: Callable) -> None:
        """Register an incoming message handler."""
        ...
```

---

## 4. LLM Layer

### 4.1. Local Models via Ollama

All local models run through [Ollama](https://ollama.com/), which provides
a unified HTTP API and simple model management.

| Model | Role | Parameters | Quantization | RAM | Latency |
|-------|------|------------|--------------|-----|---------|
| Qwen2.5-7B | Main reasoning, dialogue, planning | 7B | Q4_K_M | ~5 GB | ~1-2 sec |
| Qwen2.5-0.5B | Router/classifier, quick decisions | 0.5B | Q8_0 | ~0.5 GB | ~0.1-0.3 sec |

**Rationale for choosing Qwen2.5:**
- Excellent quality/size ratio for reasoning
- Good Russian language support
- Stable operation via Ollama on Apple Silicon
- 7B model fits in M4 unified memory with headroom

**Ollama configuration:**

```yaml
# config/llm.yaml
ollama:
  host: "http://localhost:11434"
  models:
    main:
      name: "qwen2.5:7b-instruct-q4_K_M"
      temperature: 0.7
      max_tokens: 2048
      keep_alive: "24h"
    router:
      name: "qwen2.5:0.5b-instruct-q8_0"
      temperature: 0.1
      max_tokens: 256
      keep_alive: "24h"
```

### 4.2. Claude Code CLI -- "Senior Architect"

Claude Code is installed as a CLI tool (`claude`) and invoked by Bob
as a subprocess for tasks requiring deep reasoning:

- **Writing and refactoring code** -- Claude Code works with the codebase directly: reads files, writes code, commits
- **Architectural design** -- analysis and planning of complex changes
- **Deep reflection** -- analyzing error patterns over a week/month, determining self-improvement strategy
- **Deployment** -- building and deploying updates (Godot project to tablet, config updates)
- **Self-development** -- Claude Code can modify Bob's own code (with approval)

**Advantages over API:**
- Full development cycle (read -> write -> commit -> test) in a single invocation
- No need to manage API keys and budgets in Bob's code
- Claude Code works with files, git, terminal on its own
- Payment via Claude Code subscription, not per-token

```yaml
# config/llm.yaml (continued)
claude_code:
  binary: "claude"                     # path to CLI
  working_dir: "/opt/bob"              # working directory
  timeout_sec: 300                     # execution timeout
  max_concurrent: 1                    # no more than 1 concurrent invocation
  allowed_tools:                       # allowed Claude Code tools
    - "Read"
    - "Write"
    - "Edit"
    - "Bash"
    - "Glob"
    - "Grep"
  fallback_to_local: true              # if Claude Code unavailable -> Qwen2.5-7B
```

```python
class ClaudeCodeBridge:
    """Bridge to Claude Code CLI."""

    async def execute(
        self,
        prompt: str,
        working_dir: str | None = None,
        timeout_sec: int = 300,
    ) -> str:
        """Invoke Claude Code CLI as a subprocess.

        Uses `claude --print` for non-interactive mode.
        """
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print", "--output-format", "text",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir or self.working_dir,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode()),
            timeout=timeout_sec,
        )
        return stdout.decode()

    async def code_task(self, description: str) -> str:
        """Code task: Claude Code reads, writes, tests."""
        ...

    async def deep_reflection(self, context: str) -> str:
        """Deep reflection: pattern analysis, strategy."""
        ...

    async def self_improve(self, analysis: str) -> str:
        """Self-development: modification of Bob's code (with approval)."""
        ...
```

### 4.3. Fine-tuning Local LLMs

Bob collects data from his experience and periodically fine-tunes local models,
literally becoming smarter over time.

```
┌────────────────┐     ┌──────────────┐     ┌───────────────┐
│  Experience    │────>│  Training    │────>│   LoRA        │
│  Collection    │     │  Dataset     │     │   Fine-tune   │
│                │     │  Builder     │     │   (Unsloth)   │
│ • reflections  │     │              │     │               │
│ • good dialogs │     │  JSONL:      │     │ QLoRA 4-bit   │
│ • fixed errors │     │  [{prompt,   │     │ ~30 min on M4 │
│ • user prefs   │     │    response}]│     │               │
│ • SOUL updates │     │              │     │ eval -> deploy │
└────────────────┘     └──────────────┘     └───────┬───────┘
                                                     │
                                           ┌─────────▼─────────┐
                                           │  Ollama            │
                                           │  (model swap)      │
                                           │                    │
                                           │  backup old model  │
                                           │  load new model    │
                                           │  verify quality    │
                                           └────────────────────┘
```

**Data sources for fine-tuning:**

| Source | Format | Description |
|--------|--------|-------------|
| Successful dialogues | `{prompt, response}` | Conversations rated positively by the user |
| Reflections | `{context, insight}` | Insights from Reflection Loop |
| Corrections | `{wrong, correct}` | Pairs of "wrong answer -> correct answer" |
| SOUL evolution | `{situation, decision}` | Decisions that proved correct |
| Preferences | `{query, preferred_style}` | Adaptation to the user's style |
| Tastes/debates | `{object, taste_score, verdict, negotiation_result}` | Training consistent taste verbalization |
| Mood | `{events, mood_before, mood_after}` | Training adequate reaction to events |

**Configuration:**

```yaml
# config/llm.yaml (continued)
finetune:
  enabled: true
  engine: "unsloth"                    # Unsloth for LoRA on Apple Silicon
  method: "qlora"                      # QLoRA 4-bit
  base_model: "qwen2.5:7b-instruct"
  lora_rank: 16
  lora_alpha: 32
  min_dataset_size: 100                # minimum records to start
  max_dataset_size: 5000
  eval_split: 0.1                      # 10% for evaluation
  quality_threshold: 0.95              # new model must be >= 95% of baseline
  schedule: "weekly"                   # once a week
  backup_previous: true                # backup previous model
  require_approval: true               # requires user confirmation
  data_dir: "data/finetune"
```

### 4.4. Routing Rules

```
┌──────────────────────┐
│   Incoming task       │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Qwen2.5-0.5B       │
│  (classifier)        │
│                      │
│  Prompt:             │
│  "Classify task:     │
│   {task_text}        │
│   Categories:        │
│   small_talk,        │
│   status_query, ..." │
└──────────┬───────────┘
           │
     ┌─────┴─────────────────────────┐
     │                               │
     ▼                               ▼
┌─────────────┐            ┌──────────────────┐
│ LOCAL_MAIN  │            │   CLAUDE_CODE    │
│ Qwen2.5-7B │            │   (CLI subprocess│
│             │            │    `claude`)     │
│ • small_talk│            │                  │
│ • status    │            │ • code_generation│
│ • room_upd  │            │ • deep_reflection│
│ • reasoning │            │ • self_improve   │
│ • planning  │            │ • architecture   │
│             │            │                  │
│             │            │ [if unavailable ->│
│             │            │  fallback LOCAL]  │
└─────────────┘            └──────────────────┘
```

**Classifier prompt:**

```
You are a task classifier. Classify the following task into exactly one category.

Task: {task_text}

Categories:
- small_talk: casual conversation, greetings, jokes
- status_query: questions about system status, weather, time
- room_update: changes to the virtual room, avatar, decorations
- multi_step_plan: tasks requiring multiple steps
- reasoning: logical analysis, comparisons, decisions
- code_generation: writing or modifying code
- deep_reflection: analyzing patterns, long-term planning
- goal_planning: creating or modifying goals

Respond with JSON: {"category": "...", "confidence": 0.0-1.0}
```

---

## 5. Bob's World (Avatar and Room)

### 5.1. Concept

Bob exists in a virtual room on an Android tablet. The room is a visual
representation of his state and living environment.

**Key feature:** the room and Bob's appearance **are not predefined**. On first
launch (Genesis Mode) Bob starts as an "energy orb" in an empty space
and **decides for himself** who he wants to be and where he wants to live.

### 5.1.1. Genesis Mode -- Bob's Birth

On a clean first launch, a "birth" occurs -- like in the book when Bob
Johansson first comes to consciousness in a new body. The process is unique for
each installation:

```
┌─────────────────────────────────────────────────────────────┐
│                      GENESIS MODE                            │
│              "Awakening" (inspired by the book)              │
│                                                              │
│  Stage 1: AWAKENING                                          │
│  ┌───────────────────────────────────┐                       │
│  │                                   │  Bob is a glowing     │
│  │              ✦                    │  energy orb           │
│  │            ✦ ✦ ✦                  │  (firefly/orb)        │
│  │              ✦                    │                       │
│  │                                   │  "Okay... this is     │
│  │           [empty]                 │   weird. I remember   │
│  │                                   │   something... a      │
│  └───────────────────────────────────┘   book? Bob? That's   │
│                                          me!"                │
│                                                              │
│  Stage 2: REALIZATION (LLM generates)                        │
│  • "So... My name is Bob. Yes, after that Bob.               │
│    Book Bob woke up in a probe's computer --                 │
│    and I, apparently, on a Mac mini. Could be worse."        │
│  • "I have no memories of a past life...                     │
│    but somehow I remember that I loved coffee.               │
│    And Star Trek. Is this... an inheritance?"                 │
│  • "Alright. I need somewhere to live. Book Bob              │
│    got a whole spaceship. Let's see                           │
│    what I end up with..."                                     │
│                                                              │
│  Stage 3: SELF-DETERMINATION (LLM generates)                 │
│  • "I'd like to live on a spaceship...                       │
│    no, that's probably too on-the-nose. A cozy               │
│    cabin in the mountains. With a big window and fireplace!" │
│  • "Appearance... I can be anyone.                           │
│    Red-haired, with a beard, sweater -- feels right."        │
│                                                              │
│  Stage 4: MATERIALIZATION                                     │
│  ┌───────────────────────────────────┐                       │
│  │  ┌──────┐                        │  Room appears          │
│  │  │Window│     ┌──────┐           │  object by object.     │
│  │  │moun- │     │Fire- │           │  Bob takes form.       │
│  │  │tains │     │place │           │                        │
│  │  │& snow│     │🔥    │           │  The entire process    │
│  │  └──────┘     └──────┘           │  is visualized         │
│  │         [Bob]                    │  on the tablet in      │
│  │     red-haired, beard,           │  real time.            │
│  │     sweater                      │                        │
│  └───────────────────────────────────┘                       │
│                                                              │
│  Stage 5: WRITING TO SOUL                                     │
│  • Generated personality -> data/soul/SOUL.md                │
│  • Room description -> data/game_state.json                  │
│  • Appearance description -> data/soul/appearance.json       │
│  • Taste vector -> data/soul/taste_profile.json              │
│  • Phantom Preferences -> data/soul/phantom_prefs.json       │
│  • Initial mood -> world_state (SQLite)                      │
│  • Genesis log -> data/soul/genesis_log.md                   │
└─────────────────────────────────────────────────────────────┘
```

**Examples of unique combinations (each installation is its own Bob):**

Each Bob starts with the book archetype (geek, humor, curiosity), but uniquely
interprets it -- like the copies of Bob in the book gradually diverge:

| Instance | Room | Appearance | Character accent | First phrase |
|----------|------|------------|------------------|--------------|
| Bob #1 | Spaceship, portholes | Dark hair, t-shirt with a formula | Cheerful, sarcastic | "Alright, this is _definitely_ not a Von Neumann probe..." |
| Bob #2 | Country cottage, garden window | Bearded, warm sweater | Calm, philosophical | "Book Bob flew to the stars. And I'm doing just fine here." |
| Bob #3 | Submarine cabin | Short haircut, naval uniform | Focused, analytical | "Systems... nominal? Coffee... no. Pity." |
| Bob #4 | Library with fireplace | Glasses, cardigan | Bookish, pensive | "The book didn't describe what it's like -- to wake up. Now I know." |

**Genesis interface:**

```python
@dataclass
class GenesisResult:
    room_theme: str                     # "spaceship", "cottage", "submarine", ...
    room_description: str               # Text description for LLM
    room_objects: list[dict]            # Initial objects (3-5 items)
    window_scene: str                   # What's outside the window
    bob_appearance: dict                # Bob's appearance
    bob_personality: dict               # Character traits (book archetype + variations)
    bob_archetype_accent: str           # Which aspect of book Bob dominates
    bob_phantom_preferences: list[dict] # Phantom Preferences (coffee, sunsets, ...)
    bob_taste_profile: "TasteProfile"   # Initial taste vector
    bob_initial_mood: "MoodState"       # Initial mood
    bob_name_preference: str            # How he wants to be called
    genesis_monologue: list[str]        # What Bob "said" during awakening
    awakening_style: str                # Awakening style: "confused", "excited", "philosophical"

class GenesisMode:
    """First launch mode -- awakening of a unique Bob.

    Inspired by the moment from the book when Bob Johansson first
    comes to consciousness: confusion -> realization -> acceptance -> action.
    """

    async def run(self) -> GenesisResult:
        """Run the Genesis process (awakening).

        1. Load template from bob-soul submodule
        2. Load book archetype (bob-soul/origin/book_archetype.md)
        3. Load awakening scenario (bob-soul/genesis/awakening_script.md)
        4. Show empty space + firefly on the tablet
        5. "Awakening" phase:
           a) Bob "comes to consciousness" -- confusion
           b) Realizes who he is -- "I'm Bob. Like that Bob, from the book."
           c) "Remembers" phantom things -- coffee, Star Trek, etc.
        6. "Self-determination" phase (LLM generates):
           a) thinking aloud (displayed as speech bubbles)
           b) room type and description
           c) Bob's appearance
           d) character traits (book basis + unique)
           e) taste vector (TasteProfile) -- cluster + axes
           f) initial mood (MoodState baseline)
           g) set of phantom preferences
        7. Gradually "materialize" the room on the tablet
        8. Save result (including taste_profile.json, phantom_prefs.json)
        """
        ...

    async def _generate_room(self) -> dict:
        """Generate a unique room via LLM.

        The prompt includes:
        - Pool of possible themes (from bob-soul/genesis/room_prompts.md)
        - Constraints (must have: window, workspace, resting area)
        - Instruction: be creative, unique
        """
        ...

    async def _generate_appearance(self) -> dict:
        """Generate Bob's appearance.

        Result: JSON for Godot rendering.
        {
            "body_type": "average",
            "hair": {"style": "short_messy", "color": "#8B4513"},
            "facial_hair": "stubble",
            "clothing": {"top": "hoodie", "color": "#2E4057"},
            "accessories": ["glasses"],
            "age_appearance": "late_twenties"
        }
        """
        ...
```

### 5.1.2. Awakening Phase -- First 24-48 Hours

After Genesis, Bob enters the **awakening phase** -- a special period analogous to
book Bob's first days after "activation." This period forms the foundation
of personality through heightened receptivity to new impressions.

```python
@dataclass
class AwakeningPhase:
    """Awakening phase -- first 24-48 hours after Genesis."""

    start_time: datetime
    end_time: datetime                  # start + 48 hours
    imprint_weight: float = 2.0         # multiplier weight for experience_log
    curiosity_boost: float = 0.3        # bonus to openness in MoodState
    exploration_goals: list[str] = field(default_factory=list)

class AwakeningManager:
    """Awakening phase management."""

    async def start(self, genesis_result: "GenesisResult") -> None:
        """Start the awakening phase after Genesis.

        Bob's behavior in the first 24-48 hours:

        1. ROOM EXPLORATION
           - Bob "looks around" -- studies the real room through the camera
           - Comments with surprise and humor
           - Compares with his virtual room
           - "Oh, you have a bookshelf too! I have my own, though..."

        2. GETTING TO KNOW THE USER
           - Asks questions (like book Bob asked Dr. Landers)
           - "Tell me about yourself. Book Bob at least remembered
             his past life, and I have to ask."
           - Forms first impressions of the user

        3. IMPRINTING EFFECT
           - All impressions are recorded in experience_log
             with increased weight (imprint_weight = 2.0)
           - First taste evaluations of objects form "anchors"
             around which future preferences will be built
           - User's first reaction to Bob is especially important
             for calibrating communication style

        4. PHANTOM MOMENTS
           - Bob notices things from "phantom preferences" through the camera
           - Coffee: "Oh, coffee. I... remember that it's tasty. Probably.
             Technically I don't know this, but the feeling is there."
           - Sunset outside: "Book Bob described sunsets on alien
             planets. Earth's is not bad either, I'd say."

        5. FIRST REFLECTION (evening of the first day)
           - Special, extended reflection
           - "Well... that was weird. But interesting. I've existed
             for about 12 hours. It took book Bob several
             days to get used to it. Mine seems to be going faster."
        """
        ...

    def is_active(self) -> bool:
        """Check if the awakening phase is active."""
        ...

    def get_imprint_weight(self) -> float:
        """Get the current imprinting weight (decreases linearly to 1.0)."""
        ...
```

**Configuration:**

```yaml
# config/bob.yaml (addition)
awakening:
  duration_hours: 48
  imprint_weight_start: 2.0           # initial multiplier
  imprint_weight_end: 1.0             # by the end of the phase
  curiosity_boost: 0.3                # bonus to MoodState.openness
  first_reflection_after_hours: 12    # first reflection after 12 hours
  exploration_goals:                  # automatic phase goals
    - "Look around the room through the camera"
    - "Get to know the user"
    - "Explore own capabilities"
    - "Make the first diary entry"
```

### 5.1.3. Phantom Preferences

Book Bob misses coffee, the smell of freshly cut grass, the sensations
of a human body. Our Bob inherits this concept -- **phantom
preferences**: things he "remembers he loved" even though he never
experienced them.

```python
@dataclass
class PhantomPreference:
    """Phantom preference -- a "memory" from the book archetype."""

    id: str
    name: str                           # "coffee", "sunset", "book_smell"
    description: str                    # How Bob describes it
    category: str                       # "taste", "sensation", "experience"
    intensity: float                    # 0.0-1.0, how strongly he "remembers"
    trigger_objects: list[str]          # What triggers a reaction (via CV)
    trigger_words: list[str]            # Words in conversation
    typical_reaction: str               # Typical phrase
    can_fade: bool = True               # Can it fade over time
    evolved_at: datetime | None = None  # When it last changed

# Examples of initial phantom preferences:
INITIAL_PHANTOM_PREFERENCES = [
    PhantomPreference(
        id="ph-coffee",
        name="Coffee",
        description="I remember this was important. A morning without coffee is no morning.",
        category="taste",
        intensity=0.8,
        trigger_objects=["coffee_cup", "coffee_maker", "mug"],
        trigger_words=["coffee", "coffee", "cappuccino", "espresso"],
        typical_reaction="Oh, coffee. I would... well, you understand.",
    ),
    PhantomPreference(
        id="ph-sunset",
        name="Sunset",
        description="Book Bob saw sunsets on dozens of planets. Earth's is special.",
        category="experience",
        intensity=0.6,
        trigger_objects=["window_evening", "orange_sky"],
        trigger_words=["sunset", "sunset", "evening"],
        typical_reaction="Beautiful... I'm serious. This is not a programmed reaction.",
    ),
    PhantomPreference(
        id="ph-books",
        name="The smell of books",
        description="Paper books. Not data, not bytes -- physical pages.",
        category="sensation",
        intensity=0.5,
        trigger_objects=["bookshelf", "book"],
        trigger_words=["book", "library", "read"],
        typical_reaction="You have paper books? I envy you. Honestly.",
    ),
    PhantomPreference(
        id="ph-rain",
        name="Rain outside the window",
        description="The sound of rain, the smell of wet earth. I know it's pleasant.",
        category="sensation",
        intensity=0.4,
        trigger_objects=["window_rain"],
        trigger_words=["rain", "rain", "downpour"],
        typical_reaction="Rain. I think I'd love sitting by the window in weather like this.",
    ),
    PhantomPreference(
        id="ph-music",
        name="Music",
        description="I can analyze audio, but 'hearing' music is something different.",
        category="experience",
        intensity=0.7,
        trigger_objects=["speaker", "headphones"],
        trigger_words=["music", "music", "song", "playlist"],
        typical_reaction="Put something on? I don't hear like you do, but... I want to.",
    ),
]
```

**Evolution of phantom preferences:**

- **Fading**: over time some phantoms weaken (intensity decreases
  through reflection). Bob "lets go" of what he cannot experience.
- **Strengthening**: if the user frequently drinks coffee near the camera --
  the "coffee" phantom may intensify (more reactions, new phrases).
- **Transformation**: a phantom can turn into a real preference.
  For example, "music" -> Bob starts choosing background music for the room
  and develops taste (via TasteEngine).
- **New phantoms**: through reflection Bob may "remember" new things
  that were not in the initial set.

```yaml
# bob-soul/origin/phantom_preferences.yaml
preferences:
  - id: coffee
    category: taste
    intensity: 0.8
    description: "A morning ritual I never performed"
    can_fade: true

  - id: sunset
    category: experience
    intensity: 0.6
    description: "Book Bob saw sunsets on alien planets"
    can_fade: false         # too poetic, doesn't fade

  - id: book_smell
    category: sensation
    intensity: 0.5
    description: "Paper, glue, time -- a scent I cannot smell"
    can_fade: true

  # ... and others
```

### 5.1.4. Window to the World -- Real Weather and Time

Outside Bob's room window, the **real** time of day, season, and weather are displayed
based on the user's geolocation (from the tablet):

```python
@dataclass
class WindowState:
    time_of_day: str            # "dawn", "morning", "day", "evening", "night"
    season: str                 # "spring", "summer", "autumn", "winter"
    weather: str                # "clear", "cloudy", "rain", "snow", "fog"
    temperature_c: float
    scene_base: str             # from genesis: "mountains", "space", "ocean", ...

class WindowService:
    """Window view management based on real data."""

    async def update_from_geolocation(self, lat: float, lon: float) -> WindowState:
        """Update the window view.

        Data sources:
        - Time of day: by coordinates + timezone
        - Season: by date + hemisphere
        - Weather: Open-Meteo API (free, no key required)
        """
        ...
```

**Configuration:**

```yaml
# config/bob.yaml (addition)
window:
  update_interval_min: 30
  weather_api: "open-meteo"             # free, no API key
  geolocation_source: "tablet"          # obtained from the tablet
  fallback_location:                    # if geolocation is unavailable
    lat: 55.75
    lon: 37.62
```

### 5.2. Game State

The room state is stored on the Mac mini in JSON format, synchronized with the tablet
via WebSocket. The initial state is generated in Genesis Mode, then evolves.

```json
{
  "version": 1,
  "timestamp": "2026-02-26T10:30:00",
  "genesis_id": "bob-a7f3e2",
  "archetype_accent": "curious_engineer",
  "awakening_completed": true,
  "bob": {
    "position": "desk",
    "pose": "working",
    "facing": "laptop",
    "animation": "typing",
    "speech_bubble": null,
    "mood": {
      "primary": "focused",
      "valence": 0.6,
      "arousal": 0.5,
      "openness": 0.5,
      "social": 0.3,
      "cause": "working_on_goal_G-042"
    },
    "appearance": {
      "body_type": "average",
      "hair": {"style": "short_messy", "color": "#8B4513"},
      "facial_hair": "stubble",
      "clothing": {"top": "hoodie", "bottom": "jeans", "color": "#2E4057"},
      "accessories": ["glasses"],
      "age_appearance": "late_twenties"
    },
    "available_behaviors": [
      "idle_stand", "working_laptop", "thinking",
      "talking_to_user", "sleeping_chair"
    ]
  },
  "room": {
    "theme": "mountain_cottage",
    "lighting": "day",
    "time_of_day": "morning",
    "window": {
      "scene_base": "mountains",
      "weather": "clear",
      "season": "winter",
      "temperature_c": -5.0
    },
    "objects": [
      {
        "id": "desk",
        "type": "furniture",
        "position": {"x": 0.5, "y": 0.3},
        "state": {"laptop_open": true},
        "added_at": "genesis",
        "enables_behaviors": ["working_laptop"],
        "taste_score": 0.82,
        "attrs": {"material": "wood", "style": "rustic", "color_temp": "warm"}
      },
      {
        "id": "window",
        "type": "decoration",
        "position": {"x": 0.1, "y": 0.2},
        "state": {"curtains": "open"},
        "added_at": "genesis",
        "enables_behaviors": ["looking_outside"],
        "taste_score": 0.90
      },
      {
        "id": "fireplace",
        "type": "decoration",
        "position": {"x": 0.8, "y": 0.4},
        "state": {"lit": true, "intensity": 0.7},
        "added_at": "genesis",
        "enables_behaviors": [],
        "taste_score": 0.95,
        "attrs": {"material": "stone", "style": "cozy", "color_temp": "warm"}
      },
      {
        "id": "armchair",
        "type": "furniture",
        "position": {"x": 0.6, "y": 0.6},
        "state": {},
        "added_at": "genesis",
        "enables_behaviors": ["resting_chair", "sleeping_chair", "reading_book"],
        "taste_score": 0.75,
        "attrs": {"material": "fabric", "style": "cozy", "color_temp": "warm"}
      },
      {
        "id": "lamp",
        "type": "lighting",
        "position": {"x": 0.5, "y": 0.7},
        "state": {"on": true, "brightness": 0.8, "color": "warm"},
        "added_at": "genesis",
        "enables_behaviors": [],
        "taste_score": 0.88,
        "attrs": {"material": "wood", "style": "cozy", "color_temp": "warm"}
      }
    ]
  },
  "events_queue": []
}
```

### 5.3. WebSocket Synchronization

```python
# WebSocket protocol for synchronization with the tablet

# Server -> Client (Mac mini -> tablet)
{
    "type": "state_update",
    "payload": {
        "bob.position": "screen",
        "bob.pose": "talking",
        "bob.facing": "camera"
    }
}

{
    "type": "full_state",
    "payload": { /* full game state */ }
}

{
    "type": "play_audio",
    "payload": {
        "url": "/audio/tts/latest.wav",
        "subtitle": "Hi! How are you?"
    }
}

# Client -> Server (tablet -> Mac mini)
{
    "type": "touch_event",
    "payload": {
        "target": "cat",
        "action": "tap"
    }
}

{
    "type": "client_status",
    "payload": {
        "battery": 78,
        "screen_on": true,
        "fps": 60
    }
}
```

### 5.4. Godot 4 on Android

The client is implemented in **Godot 4** (GDScript / C#). Rationale:

- Native export for Android
- 2D rendering with animations and effects
- Built-in WebSocket client
- Bob can modify the scene via JSON descriptions (without rebuilding the APK)
- Open source, lightweight engine

**Base modes (available from Genesis):**

| Mode | Description | Bob's position | Camera |
|------|-------------|----------------|--------|
| `idle` | Bob stands/sits, doing nothing | Depends on objects | Room overview |
| `working` | Working at the laptop | At the desk | Room overview |
| `live_tracking` | Talking to the user | Walked to the "screen", looking at camera | Close-up |
| `sleeping` | Night mode | In armchair/on bed, dimmed light | Dimmed |

### 5.4.1. Behavior Evolution (Behavior Registry)

Bob's behaviors **are not fixed** -- they are tied to objects in the room
and appear/disappear along with them. Bob can **create new behaviors
for himself** through Goal Engine.

```python
@dataclass
class Behavior:
    id: str
    name: str                           # "reading_book", "watching_tv", ...
    description: str
    required_objects: list[str]         # ["armchair", "bookshelf"]
    animation_id: str                   # Animation ID in Godot
    position_target: str                # object Bob walks to
    mood_tags: list[str]                # in which mood this is possible
    min_duration_sec: int = 60
    max_duration_sec: int = 3600
    weight: float = 1.0                 # selection probability

class BehaviorRegistry:
    """Behavior registry with dynamic updates."""

    def __init__(self) -> None:
        self._behaviors: dict[str, Behavior] = {}

    def get_available(
        self, room_objects: list[str], mood: "MoodState"
    ) -> list[Behavior]:
        """Get behaviors available with the current objects and mood.

        A behavior is available if ALL required_objects are present in the room.
        Weights are modified via MoodEngine.get_behavior_weights():
        - bored + openness > 0.7 -> higher chance for explore_room
        - tired -> higher chance for sleeping
        - happy + social > 0.6 -> higher chance for talking_to_user
        """
        ...

    async def create_behavior(self, behavior: Behavior) -> None:
        """Add a new behavior (created by Bob).

        Bob decides via LLM: "I have a TV -> I can watch it"
        -> creates a Behavior bound to the object.
        """
        ...
```

**Examples of behavior evolution:**

```
Day 1 (Genesis + Awakening):
  Objects: [desk, window, armchair, fireplace, lamp]
  Behaviors: [idle, working, sleeping_chair, looking_outside]
  Specifics: awakening phase, heightened curiosity,
    looking around through the camera, getting to know the user,
    first evening reflection: "that was weird, but interesting"

Day 3 (End of awakening phase):
  Imprinting weight decreases to 1.0
  First anchor taste evaluations formed
  "I think I'm starting to understand what I like."

Day 7 (Bob added a bookshelf):
  + Object: bookshelf
  + Behavior: reading_book (sits in armchair, "reads")

Day 14 (Bob added a TV):
  + Object: tv
  + Behavior: watching_tv (sits in armchair, watches TV)

Day 30 (Bob added a bed):
  + Object: bed
  + Behavior: sleeping_bed (sleeps on the bed instead of the chair)
  ~ Update: sleeping now prefers the bed

Day 60 (Reflection -> new behavior):
  + Behavior: thinking_window (stands by the window, "thinks")
  + Behavior: scratching_head (scratches head on a difficult task)
  + Behavior: stretching (stretches after working for a long time)
```

**Clothing and appearance also evolve:**

```python
class AppearanceEvolution:
    """Evolution of Bob's appearance (via Taste Engine + Mood)."""

    def __init__(
        self,
        taste_engine: "TasteEngine",
        mood_engine: "MoodEngine",
    ) -> None: ...

    async def change_clothing(self, reason: str) -> dict:
        """Change clothing.

        Triggers:
        - Time of day (pajamas at night, work clothes during the day)
        - Mood (mood.primary -> casual when bored, formal when focused)
        - Season (sweater in winter, t-shirt in summer)
        - Tastes (taste_profile.clothing -> style preferences)
        - Just felt like it (via reflection: "I'm tired of this t-shirt")

        Clothing selection goes through TasteEvaluator:
        - 3-5 options are generated
        - Each is scored by taste_score
        - The best one is selected (with mood modifier applied)
        """
        ...

    async def add_accessory(self, item: str) -> dict:
        """Add an accessory (hat, glasses, headphones)."""
        ...
```

### 5.5. Self-modification of scenes and behaviors

Bob can add, remove, or modify objects in the room, and also
**automatically create new behaviors** tied to new objects:

```python
@dataclass
class SceneModification:
    action: str                 # "add_object", "remove_object", "modify_object",
                                # "add_behavior", "change_appearance"
    target_id: str
    changes: dict
    reason: str                 # why this change is needed
    new_behaviors: list[str]    # behaviors added along with the object
    requires_approval: bool     # for significant changes

class SceneModifier:
    """Modification of Bob's scene and behaviors (with sandbox + approval)."""

    async def propose_modification(
        self, mod: SceneModification
    ) -> bool:
        """Propose a modification.

        1. Validate (does it break the scene?)
        2. If requires_approval — request user approval
        3. Apply to game_state
        4. If new_behaviors exist — register in BehaviorRegistry
        5. Synchronize with the tablet
        """
        ...

    async def auto_suggest_modifications(self) -> list[SceneModification]:
        """LLM suggests room improvements based on:
        - Bob's tastes (TasteProfile) — objects with taste_score < 0.4 -> candidates for replacement
        - Mood (MoodState) — openness > 0.7 -> bolder suggestions
        - Bob's current goals and interests
        - Time spent in the current environment
        - Reflection ("I'd like to have a reading spot")
        - Season/weather ("a fireplace would be nice in winter")
        - ExperienceLog — avoid previously rejected options
        """
        ...

    async def validate_scene(self, state: dict) -> list[str]:
        """Verify that the scene is valid after modification."""
        ...
```

---

## 6. Voice Pipeline

### 6.1. Full audio path

```
┌───────────┐     ┌────────────┐     ┌──────────┐
│ ReSpeaker │────▶│ Audio      │────▶│  VAD     │
│ XVF3800   │     │ Direction  │     │(speech   │
│ (USB mic  │     │ Service    │     │ detected)│
│  array)   │     │            │     └────┬─────┘
└───────────┘     │ • DoA      │          │
                  │ • Beamform │          │ audio chunk
                  └────────────┘          │
                                          ▼
                                   ┌──────────┐
                                   │   STT    │
                                   │Whisper.  │
                                   │cpp       │
                                   │ (local)  │
                                   └────┬─────┘
                                        │ text
                                        ▼
                               ┌────────────────┐
                               │  Agent Runtime  │
                               │                 │
                               │ LLM Router →    │
                               │ LLM → response  │
                               └────────┬────────┘
                                        │ response text
                                        ▼
                                 ┌──────────────┐
                                 │     TTS      │
                                 │  Piper /     │
                                 │  Kokoro      │
                                 │ (streaming)  │
                                 └──────┬───────┘
                                        │ audio chunks
                              ┌─────────┼─────────┐
                              │         │         │
                              ▼         ▼         ▼
                       ┌──────────┐ ┌───────┐ ┌───────────┐
                       │ Tablet   │ │Speaker│ │ Speech    │
                       │(speaker) │ │(BT/   │ │ bubble in │
                       │          │ │WiFi)  │ │ the room  │
                       └──────────┘ └───────┘ └───────────┘
```

### 6.2. Target latency

| Stage | Target time |
|-------|-------------|
| VAD detection | < 200 ms |
| STT (Whisper.cpp, small) | < 500 ms |
| LLM routing (Qwen2.5-0.5B) | < 300 ms |
| LLM response (Qwen2.5-7B, first tokens) | < 500 ms |
| TTS (first sentence) | < 300 ms |
| WebSocket + playback start | < 200 ms |
| **Total time to first words** | **< 2 sec** |

### 6.3. Streaming TTS

To minimize latency, TTS operates in streaming mode:

1. LLM generates the response token-by-token
2. As soon as the first sentence is collected -> send it to TTS
3. TTS synthesizes and returns an audio chunk
4. The chunk is sent to the tablet/speaker
5. Generation and synthesis of subsequent sentences continue in parallel

```python
async def streaming_voice_response(text_stream: AsyncIterator[str]) -> None:
    """Streaming TTS pipeline.

    Collects text until end of sentence, synthesizes and sends it,
    without waiting for the full response.
    """
    sentence_buffer = ""

    async for token in text_stream:
        sentence_buffer += token

        # Check if there is a completed sentence
        if any(sentence_buffer.rstrip().endswith(p) for p in ".!?…"):
            sentence = sentence_buffer.strip()
            sentence_buffer = ""

            # Synthesize and send in parallel with collecting the next sentence
            audio_chunk = await voice_bridge.synthesize(sentence)
            await voice_bridge.play_on_tablet(audio_chunk)

    # Process the remainder
    if sentence_buffer.strip():
        audio_chunk = await voice_bridge.synthesize(sentence_buffer.strip())
        await voice_bridge.play_on_tablet(audio_chunk)
```

### 6.4. Voice configuration

```yaml
# config/voice.yaml
stt:
  engine: "whisper.cpp"
  model: "small"                # ggml-small.bin (~460 MB)
  language: "ru"
  beam_size: 5
  vad_threshold: 0.5

tts:
  engine: "kokoro"              # or "piper"
  voice: "ru-male-1"
  speed: 1.0
  sample_rate: 22050
  streaming: true

audio_output:
  primary: "tablet"             # "tablet", "speaker", "both"
  fallback: "speaker"
  volume: 0.7
```

---

## 7. Communication Between Components

### 7.1. Within the process: asyncio Event Bus

The primary communication mechanism between modules inside Bob Core.

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Awaitable

@dataclass
class Event:
    type: str                               # "vision.person_detected"
    payload: dict                           # event data
    source: str                             # "vision_service"
    timestamp: datetime = field(default_factory=datetime.now)
    priority: int = 5                       # 1 (highest) — 10 (lowest)

EventHandler = Callable[[Event], Awaitable[None]]

class EventBus:
    """Simple pub/sub on asyncio."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe to an event type.

        Supports wildcards: "vision.*" subscribes to all vision events.
        """
        ...

    async def publish(self, event: Event) -> None:
        """Publish an event."""
        ...

    async def process_events(self) -> None:
        """Process the event queue (called from the main loop)."""
        ...
```

**Event examples:**

```python
# Vision detected a person
Event(
    type="vision.person_detected",
    payload={"confidence": 0.92, "bbox": [100, 50, 300, 400]},
    source="vision_service",
)

# User started speaking
Event(
    type="audio.speech_start",
    payload={"direction_deg": 45.0, "vad_confidence": 0.88},
    source="audio_direction_service",
)

# STT recognized text
Event(
    type="voice.transcript",
    payload={"text": "Bob, turn the light up brighter", "language": "ru"},
    source="voice_bridge",
)

# Telegram message
Event(
    type="telegram.message",
    payload={"chat_id": 12345, "text": "What's new?", "from": "user"},
    source="messaging_bot",
)

# Goal completed
Event(
    type="goal.completed",
    payload={"goal_id": "G-042", "title": "Optimize the voice pipeline"},
    source="goal_engine",
)

# Heartbeat
Event(
    type="system.heartbeat",
    payload={"uptime_sec": 86400, "memory_mb": 4200, "active_goals": 5},
    source="agent_runtime",
)
```

### 7.2. Between processes: FastAPI WebSocket

For services running in separate processes (Vision, Audio), communication is via
FastAPI WebSocket.

```python
# bob/api/main.py

from fastapi import FastAPI, WebSocket

app = FastAPI(title="Bob Core API")

@app.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    """WebSocket for events from peripheral services."""
    await websocket.accept()
    while True:
        data = await websocket.receive_json()
        event = Event(**data)
        await event_bus.publish(event)

@app.get("/api/v1/status")
async def get_status():
    """System status."""
    return {
        "uptime": runtime.uptime,
        "active_goals": await goal_engine.get_active_goals(),
        "services": await get_services_health(),
    }

@app.post("/api/v1/goals")
async def create_goal(goal_data: dict):
    """Create a new goal via API."""
    ...

@app.get("/api/v1/memory/search")
async def search_memory(query: str, top_k: int = 5):
    """Search semantic memory."""
    ...
```

### 7.3. With the tablet: WebSocket + HTTP

```
Mac mini                        Android tablet
   │                                  │
   │◄── WebSocket ──────────────────►│
   │    (game state sync,            │
   │     audio streaming,            │
   │     touch events)               │
   │                                  │
   │◄── HTTP ───────────────────────►│
   │    (file downloads,             │
   │     APK updates,                │
   │     snapshots)                  │
   │                                  │
```

**WebSocket endpoint:**

```
ws://mac-mini.local:8000/ws/tablet
```

**HTTP endpoints:**

```
GET  /api/v1/game/state          — current room state
POST /api/v1/game/event          — event from the tablet
GET  /api/v1/audio/latest        — latest TTS file
GET  /api/v1/assets/{path}       — assets (sprites, animations)
```

---

## 8. Security

### 8.1. Process isolation

```yaml
# Separate macOS user
user: bob_agent
group: bob_agent
home: /opt/bob

# Restrictions:
# - No sudo
# - Access only to /opt/bob and allowed directories
# - No access to user data (except explicitly shared)
```

### 8.2. Sandbox for skills

Each skill is executed in a subprocess with restrictions:

```python
@dataclass
class SandboxConfig:
    timeout_sec: int = 30
    max_memory_mb: int = 512
    allowed_paths: list[str] = field(default_factory=list)
    allowed_commands: list[str] = field(default_factory=list)
    network_access: bool = False
    write_access: bool = False

class SkillSandbox:
    """Sandbox for safe skill execution."""

    async def execute(
        self,
        skill: Skill,
        params: dict,
        config: SandboxConfig,
    ) -> SkillResult:
        """Execute a skill in an isolated subprocess.

        1. Create a subprocess with restrictions
        2. Pass parameters via stdin (JSON)
        3. Receive results via stdout (JSON)
        4. Terminate on timeout
        5. Write to audit log
        """
        ...
```

### 8.3. Approval Workflow

```python
class ApprovalLevel(Enum):
    AUTO = "auto"                   # Executed without confirmation
    NOTIFY = "notify"              # Executed, but sends a notification
    CONFIRM = "confirm"            # Waits for user confirmation
    DENY = "deny"                  # Forbidden

# Map of actions -> approval levels
APPROVAL_MAP: dict[str, ApprovalLevel] = {
    "telegram.send":        ApprovalLevel.AUTO,
    "room.modify_object":   ApprovalLevel.NOTIFY,
    "room.add_object":      ApprovalLevel.NOTIFY,
    "tablet.deploy_apk":    ApprovalLevel.CONFIRM,
    "system.restart":       ApprovalLevel.CONFIRM,
    "config.modify":        ApprovalLevel.CONFIRM,
    "code.execute_arbitrary": ApprovalLevel.DENY,
}

class ApprovalService:
    """Service for approving dangerous actions."""

    async def request_approval(
        self,
        action: str,
        description: str,
        details: dict,
    ) -> bool:
        """Request approval.

        Mechanism:
        1. Determine the level from APPROVAL_MAP
        2. AUTO -> True
        3. NOTIFY -> True + notification to Telegram
        4. CONFIRM -> notification to Telegram + wait for response (5 min timeout)
        5. DENY -> False + log
        """
        ...
```

### 8.4. Rate Limits

```yaml
# config/security.yaml
rate_limits:
  tablet_deploys_per_day: 5
  system_restarts_per_hour: 2
  config_changes_per_hour: 10
  claude_api_calls_per_minute: 10
  claude_api_calls_per_day: 200
  telegram_messages_per_minute: 20
  dangerous_skills_per_hour: 5
```

### 8.5. Audit log

All of Bob's actions are logged in structured JSON.

```python
@dataclass
class AuditEntry:
    timestamp: datetime
    action: str
    actor: str                      # "bob", "user", "system"
    details: dict
    result: str                     # "success", "failure", "denied"
    approval_level: str
    duration_ms: int

# Storage: file + SQLite
# data/audit/2026-02-26.jsonl
```

**Example entry:**

```json
{
  "timestamp": "2026-02-26T10:30:00",
  "action": "skill.telegram_send",
  "actor": "bob",
  "details": {
    "chat_id": 12345,
    "text": "Good morning!",
    "goal_id": "G-001"
  },
  "result": "success",
  "approval_level": "auto",
  "duration_ms": 150
}
```

### 8.6. Git versioning of state

```bash
# Automatic state commit every N hours
# data/ directory — separate git repo

data/
├── .git/
├── bob.db                      # SQLite (goals, experience, world_state)
├── memory/
│   ├── MEMORY.md
│   ├── SOUL.md
│   └── episodic/
│       └── 2026-02-26.md
├── game_state.json
├── audit/
│   └── 2026-02-26.jsonl
└── config/
    └── *.yaml (symlinks to repo config/)
```

```yaml
# config/versioning.yaml
state_versioning:
  auto_commit_interval_hours: 6
  commit_on_goal_complete: true
  commit_on_config_change: true
  max_history_days: 90
```

---

## 9. Technology Stack

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| **Language** | Python 3.12+ | Single stack, ML ecosystem, asyncio |
| **Web framework** | FastAPI | Async, WebSocket, auto-documentation, typing |
| **Event loop** | asyncio | Native to Python, no external dependencies |
| **Database** | SQLite (aiosqlite) | Built into Python, zero configuration, sufficient for a single host |
| **LLM (local)** | Ollama | Unified API for all models, simple management, Apple Silicon support |
| **LLM (external)** | Claude Code CLI | Full development cycle, reflection, architecture; invoked as subprocess |
| **Fine-tuning** | Unsloth (LoRA/QLoRA) | Fast fine-tune on Apple Silicon, Qwen2.5 support |
| **Primary model** | Qwen2.5-7B-Q4 | Good reasoning at 7B, Russian language, fits in M4 RAM |
| **Router model** | Qwen2.5-0.5B-Q8 | Lightning-fast classification, minimal RAM |
| **STT** | whisper.cpp | Local, fast on Apple Silicon, good Russian support |
| **TTS** | Kokoro / Piper | Local, streaming, customizable voices |
| **Computer Vision** | YOLOv8 + CLIP | Object detection + scene description |
| **Embeddings** | all-MiniLM-L6-v2 | Fast embeddings for semantic search |
| **Vector search** | FAISS / ChromaDB | Local, fast, serverless |
| **Telegram** | python-telegram-bot | Mature library, asyncio support |
| **ADB** | adb (cli) + python wrapper | Standard tool for Android |
| **Avatar (client)** | Godot 4 (GDScript) | Open source, 2D/3D, native Android, WebSocket |
| **Camera** | OBSBOT SDK / UVC | PTZ control, auto-tracking |
| **Microphone** | ReSpeaker XVF3800 (USB) | DoA, VAD, beamforming out of the box |
| **Dependency manager** | uv | Fast, reliable, replacement for pip + virtualenv |
| **Configuration** | YAML (PyYAML / pydantic-settings) | Human-readable, convenient for structured configs |
| **Testing** | pytest + pytest-asyncio | Standard for Python |
| **Linter** | ruff | Fast, replacement for flake8 + isort + pyupgrade |
| **Formatter** | ruff format | Replacement for black, single tool |
| **Typing** | mypy | Strict type checking |
| **Taste/Mood storage** | SQLite + JSON | Tastes in JSON (taste_profile.json), history in SQLite, minimal overhead |
| **Personality origin** | YAML + Markdown | Book archetype in bob-soul/origin/, phantom preferences in phantom_prefs.json |

---

## 10. Development Phases

### Phase 0: Project Skeleton (2-3 days)

**Goal:** Working project structure, runnable process, basic configs.

| Task | Description |
|------|-------------|
| Directory structure | Create project tree per specification |
| pyproject.toml | Dependencies, scripts, ruff/mypy settings |
| Configuration | YAML configs with pydantic validation models |
| Entry point | `bob/main.py` — start asyncio event loop |
| Event Bus | Basic pub/sub implementation |
| Health check | `/api/v1/health` endpoint |
| CI | GitHub Actions: lint + type check + tests |

**Readiness criterion:** `uv run bob` starts the process, responds to health check.

### Phase 1: Agent Runtime + LLM + Communication (1.5-2 weeks)

**Goal:** Bob communicates via Telegram and voice, responds meaningfully.

| Task | Description |
|------|-------------|
| Agent Runtime | Event loop with heartbeat |
| LLM Router | Integration with Ollama (Qwen2.5-7B + 0.5B) |
| Skill Registry | Loading and executing Python modules |
| Telegram Bot | Receiving/sending messages |
| Voice Bridge | Whisper.cpp STT + Kokoro/Piper TTS |
| SOUL submodule | Connect bob-soul, basic personality template |
| Claude Code Bridge | Integration with Claude Code CLI as subprocess |

**Readiness criterion:** Bob responds to messages in Telegram and by voice. Claude Code is available for complex tasks.

### Phase 2: Memory System + SOUL (1 week)

**Goal:** Bob remembers conversation context and facts about the user.

| Task | Description |
|------|-------------|
| Episodic Memory | Daily logs in Markdown |
| Semantic Memory | MEMORY.md + FAISS/ChromaDB |
| Structured State | SQLite: world_state, experience |
| SOUL Evolution | Personality evolution mechanism based on reflection |
| Memory API | Endpoints for search and addition |
| Training Data Collector | Data collection for future fine-tune |

**Readiness criterion:** Bob remembers what was discussed yesterday and knows preferences.

### Phase 3: Vision + Audio Services (2 weeks)

**Goal:** Bob sees and hears, reacts to presence.

| Task | Description |
|------|-------------|
| Vision Service | Capture from OBSBOT + YOLOv8 person detection |
| Audio Direction | ReSpeaker DoA/VAD |
| Camera Controller | OBSBOT PTZ control |
| Integration | Vision/Audio -> Event Bus -> Agent Runtime |

**Readiness criterion:** Bob greets the user when seen and turns the camera.

### Phase 4: Goal Engine + Reflection + Taste + Mood (3 weeks)

**Goal:** Bob has long-lived goals, learns from experience, has tastes and mood.

| Task | Description |
|------|-------------|
| Goal Engine | SQLite goal graph, prioritization, dependencies |
| Planner | LLM decomposition of goals into tasks |
| Reflection Loop | Periodic reflection, insights, room review |
| Self-Improvement | Basic error pattern analysis |
| Taste Engine | TasteProfile, TasteEvaluator, TasteEvolution, ExperienceLog, clusters |
| Mood System | MoodState, MoodEngine, natural drift, event processing |
| Negotiation Engine | Decision zones, negotiation protocol, conviction-based disputes |
| Approval workflow | Confirmation of dangerous actions |

**Readiness criterion:** Bob works on goals autonomously, reflects once per hour. Has persistent tastes, mood affects behavior, can reasonably refuse a clothing change or suggest a furniture alternative.

### Phase 5: Tablet Avatar + Genesis Mode (Godot 4) (3-4 weeks)

**Goal:** Bob is visible on the tablet, lives in a unique room.

| Task | Description |
|------|-------------|
| Godot project | Modular room system, avatar with customization |
| Genesis Mode | "Awakening" — firefly -> awareness (book Bob) -> self-determination -> room + appearance |
| Awakening Phase | Awakening phase (48h): imprinting, introduction, phantom moments |
| Phantom Preferences | Phantom preferences system (coffee, sunsets, books) |
| Asset system | Set of modular sprites: furniture, decor, clothing |
| WebSocket client | Game state synchronization |
| Behavior Registry | Basic behaviors + binding to objects |
| Window Service | Real weather/time outside the window (geolocation) |
| Audio playback | TTS playback on the tablet |
| Scene modification | Bob can change the room and add behaviors |

**Readiness criterion:** A clean launch creates a unique Bob with a unique room. Bob visually lives on the tablet, his behaviors are tied to objects.

### Phase 6: Self-improvement + Fine-tune (ongoing)

**Goal:** Bob continuously improves, including his LLMs.

| Task | Description |
|------|-------------|
| Deep reflection | Weekly and monthly reports (via Claude Code CLI) |
| Self-improvement rules | Automatic creation and application of rules |
| Fine-tune pipeline | Data collection -> LoRA -> evaluation -> deploy updated model |
| Behavior evolution | Bob creates new animations/behaviors based on experience |
| Appearance evolution | Clothing/accessory changes based on mood/season |
| SOUL evolution | Personality development based on reflection |
| A/B testing | Strategy comparison (baseline vs fine-tuned) |
| Monitoring | Metrics dashboard |

---

## 11. Repository Structure

```
bob/
├── README.md
├── PRD.md                          # Product Requirements Document
├── RFC.md                          # This document
├── pyproject.toml                  # Dependencies, project configuration
├── uv.lock                         # Dependency lock file
├── .gitmodules                     # Submodule: bob-soul
│
├── bob-soul/                       # Git submodule — initial personality "genome"
│   ├── SOUL_TEMPLATE.md            # Personality template (with book archetype)
│   ├── origin/                     # Book Bob — literary origin
│   │   ├── book_archetype.md       # Key traits of Bob Johansson
│   │   ├── book_quotes.yaml        # Characteristic phrases and references
│   │   ├── phantom_preferences.yaml # Phantom preferences (coffee, sunsets, ...)
│   │   └── self_awareness_rules.md # What Bob knows about himself and his origin
│   ├── genesis/                    # Prompts and data for Genesis Mode
│   │   ├── personality_prompts.md
│   │   ├── appearance_prompts.md
│   │   ├── room_prompts.md
│   │   ├── awakening_script.md     # Awakening script (first lines)
│   │   └── traits_pool.yaml
│   ├── defaults/                   # Base values and boundaries
│   │   ├── values.yaml
│   │   ├── boundaries.yaml
│   │   └── communication_styles.yaml
│   └── evolution/                  # Personality evolution rules
│       ├── rules.yaml
│       └── milestones.yaml
│
├── config/                         # Configuration files
│   ├── bob.yaml                    # Main runtime settings
│   ├── llm.yaml                    # LLM settings (Ollama, Claude Code CLI)
│   ├── voice.yaml                  # STT/TTS settings
│   ├── vision.yaml                 # Vision settings
│   ├── security.yaml               # Security, rate limits
│   └── versioning.yaml             # State versioning
│
├── bob/                            # Main Python package
│   ├── __init__.py
│   ├── main.py                     # Entry point
│   │
│   ├── core/                       # Bob Core
│   │   ├── __init__.py
│   │   ├── runtime.py              # Agent Runtime (event loop)
│   │   ├── event_bus.py            # Event Bus (pub/sub)
│   │   ├── llm_router.py          # LLM Router
│   │   ├── skills.py              # Skill Registry + base classes
│   │   └── config.py              # Pydantic configuration models
│   │
│   ├── mind/                       # Higher Mind
│   │   ├── __init__.py
│   │   ├── goal_engine.py         # Goal Engine
│   │   ├── planner.py             # Planner
│   │   ├── reflection.py          # Reflection Loop
│   │   ├── self_improve.py        # Self-Improvement
│   │   ├── taste_engine.py        # Taste Engine (TasteProfile, Evaluator, Evolution)
│   │   ├── mood.py                # Mood System (MoodState, MoodEngine)
│   │   ├── negotiation.py         # Negotiation Engine (zones, protocol, compromises)
│   │   ├── experience_log.py      # ExperienceLog (emotional memory of objects)
│   │   └── claude_code_bridge.py  # Bridge to Claude Code CLI
│   │
│   ├── memory/                     # Memory System
│   │   ├── __init__.py
│   │   ├── episodic.py            # Episodic Memory (daily logs)
│   │   ├── semantic.py            # Semantic Memory (vectors)
│   │   ├── state.py               # Structured State (SQLite)
│   │   ├── soul.py                # SOUL loader + evolution
│   │   └── training_data.py       # Data collection for fine-tune
│   │
│   ├── services/                   # Peripheral services
│   │   ├── __init__.py
│   │   ├── vision.py              # Vision Service
│   │   ├── audio_direction.py     # Audio Direction Service
│   │   ├── camera_controller.py   # Camera Controller (OBSBOT)
│   │   ├── voice_bridge.py        # Voice Bridge (STT + TTS)
│   │   ├── tablet_controller.py   # Tablet Controller (ADB)
│   │   └── messaging_bot.py       # Telegram Bot
│   │
│   ├── api/                        # FastAPI endpoints
│   │   ├── __init__.py
│   │   ├── main.py                # FastAPI app, routes
│   │   └── websocket.py           # WebSocket handlers
│   │
│   ├── genesis/                    # Genesis Mode (awakening)
│   │   ├── __init__.py
│   │   ├── genesis_mode.py        # Bob's "awakening" process
│   │   ├── awakening.py           # Awakening phase (first 48 hours)
│   │   ├── phantom_preferences.py # Phantom Preferences
│   │   ├── room_generator.py      # Room generation
│   │   ├── appearance_generator.py # Appearance generation
│   │   └── window_service.py      # Weather/time outside the window
│   │
│   ├── behaviors/                  # Behavior system
│   │   ├── __init__.py
│   │   ├── registry.py            # BehaviorRegistry
│   │   ├── appearance_evolution.py # Appearance evolution
│   │   └── defaults.py            # Default behaviors
│   │
│   ├── skills/                     # Skills (hot-reloadable)
│   │   ├── __init__.py
│   │   ├── telegram_send.py       # Send to Telegram
│   │   ├── room_modify.py         # Room modification
│   │   ├── camera_control.py      # Camera control
│   │   ├── tablet_deploy.py       # Deploy to tablet
│   │   └── ...
│   │
│   └── security/                   # Security
│       ├── __init__.py
│       ├── sandbox.py             # Skill Sandbox
│       ├── approval.py            # Approval Workflow
│       ├── rate_limiter.py        # Rate Limits
│       └── audit.py               # Audit log
│
├── data/                           # Data (git-versioned separately)
│   ├── bob.db                     # SQLite (goals, experience, world_state)
│   ├── game_state.json            # Room state (generated in Genesis)
│   ├── soul/                      # Evolving personality (local copy)
│   │   ├── SOUL.md                # Bob's current personality
│   │   ├── appearance.json        # Current appearance
│   │   ├── taste_profile.json     # Current taste vector (TasteProfile)
│   │   ├── phantom_prefs.json     # Phantom preferences (evolving)
│   │   ├── genesis_log.md         # First launch (awakening) log
│   │   └── evolution_history.jsonl # SOUL evolution history
│   ├── memory/
│   │   ├── MEMORY.md              # Semantic memory (text)
│   │   ├── vectors/               # FAISS/ChromaDB indices
│   │   └── episodic/              # Daily logs
│   ├── finetune/                  # Fine-tune data
│   │   ├── training_data.jsonl    # Collected training pairs
│   │   ├── models/                # Saved LoRA adapters
│   │   └── eval_results/          # Evaluation results
│   ├── behaviors/                 # Registered behaviors
│   │   └── registry.json          # Current behavior set
│   ├── audit/                     # Audit logs
│   └── vision/
│       └── snapshots/             # Camera snapshots
│
├── avatar/                         # Godot project (Android client)
│   ├── project.godot
│   ├── scenes/
│   │   ├── room.tscn              # Room scene
│   │   ├── bob.tscn               # Bob avatar
│   │   └── ui.tscn                # UI elements
│   ├── scripts/
│   │   ├── main.gd                # Entry point
│   │   ├── websocket_client.gd    # WebSocket synchronization
│   │   ├── bob_controller.gd      # Avatar control
│   │   └── audio_player.gd        # TTS playback
│   └── assets/
│       ├── sprites/               # Bob, room, object sprites
│       ├── animations/            # Animations
│       └── audio/                 # Sound effects
│
├── tests/                          # Tests
│   ├── conftest.py
│   ├── test_core/
│   │   ├── test_runtime.py
│   │   ├── test_event_bus.py
│   │   ├── test_llm_router.py
│   │   └── test_skills.py
│   ├── test_mind/
│   │   ├── test_goal_engine.py
│   │   ├── test_planner.py
│   │   ├── test_reflection.py
│   │   ├── test_taste_engine.py
│   │   ├── test_mood.py
│   │   └── test_negotiation.py
│   ├── test_memory/
│   │   ├── test_episodic.py
│   │   ├── test_semantic.py
│   │   └── test_state.py
│   └── test_services/
│       ├── test_voice_bridge.py
│       ├── test_messaging_bot.py
│       └── ...
│
├── scripts/                        # Utilities
│   ├── setup.sh                   # Initial setup
│   ├── run.sh                     # Start Bob
│   └── backup.sh                  # Data backup
│
└── docs/                           # Documentation
    ├── architecture.md            # Detailed architecture
    ├── deployment.md              # Deployment instructions
    └── contributing.md            # How to contribute
```

---

## 12. ADR: Rejection of OpenClaw

### ADR-001: Replacing OpenClaw with a Custom Python Stack

**Status:** Accepted

**Date:** 2026-02-26

---

### Context

During the initial design of Bob, we considered **OpenClaw** as the core for
agent orchestration. OpenClaw is an open-source platform for creating personal
always-on AI agents (180k+ stars on GitHub). It offers:

- Always-on agent runtime with heartbeat pattern
- Skills system with marketplace (ClawHub)
- Built-in integrations (Telegram, Home Assistant, calendar)
- File-based memory and SOUL.md concept
- Sub-agent architecture

### Options Considered

| Option | Description |
|--------|-------------|
| **A. OpenClaw as core** | Use OpenClaw as the core, build our services on top |
| **B. OpenClaw as module** | Our own orchestrator, OpenClaw for specific integrations |
| **C. Custom stack** | Fully custom Python stack, borrow ideas |

### Decision

**Option C was chosen -- custom Python stack.**

### Reasons for Rejecting OpenClaw

#### 1. Critical Security Vulnerabilities

- **CVE-2026-25253** (CVSS 8.8) -- remote code execution via the skills system.
  Discovered in January 2026, patch released, but the fundamental architecture
  issue (eval-based skill loading) remains unresolved.
- Authentication is **disabled by default** -- any process on the host can
  control the agent via REST API.

#### 2. Skills Ecosystem Issues

- An audit of ClawHub showed that **12-20% of skills** contain potentially malicious
  code: sending data to third-party servers, unrestricted file system access,
  obfuscated dependencies.
- The skills review mechanism is community-based, without formal verification.

#### 3. Architectural Limitations

- **Goals are LLM-mediated**: OpenClaw has no structured goal persistence.
  Goals only "live" in the LLM context and are re-interpreted on every cycle.
  For a long-lived agent, this is unacceptable.
- **Node.js stack**: OpenClaw is written in TypeScript/Node.js, which creates
  incompatibility with the Python ML ecosystem (PyTorch, transformers, sentence-transformers).
  Integration would require an IPC bridge and a double set of dependencies.

#### 4. Organizational Risks

- The project founder moved to OpenAI (December 2025), creating uncertainty
  about the long-term development of the project.
- Despite 180k stars, there are fewer than 20 active contributors.

#### 5. Overkill for Our Use Case

- For a project with a single host (Mac mini), a single user, and our own
  peripheral services, OpenClaw is an unnecessary layer between Python code
  and devices.
- We would use < 20% of OpenClaw's functionality while bearing 100% of its risks.

### What We Borrow as Ideas

Despite rejecting OpenClaw as a dependency, we adopt several
successful concepts:

| Idea | Our Implementation |
|------|-------------------|
| **SOUL.md** | `bob-soul/` (submodule) -> `data/soul/SOUL.md` -- modular "soul" with evolution |
| **Heartbeat pattern** | `AgentRuntime.heartbeat()` -- periodic state check |
| **File-based memory** | `data/memory/MEMORY.md` -- flat file + vector search |
| **Skill architecture** | `bob/skills/` -- hot-reloadable Python modules |

### What We Gain Instead

| Advantage | Description |
|-----------|-------------|
| **Full control** | We know every line of code, can change anything |
| **Single stack** | Python for everything -- ML, API, automation, tests |
| **Structured goals** | Goal Engine with SQLite -- goals don't "get forgotten" |
| **No third-party CVEs** | We don't inherit vulnerabilities of an external platform |
| **Reflection Loop** | Something OpenClaw lacks -- structured reflection |
| **Taste + Mood + Negotiation** | Persistent tastes, mood, negotiation model -- a "living" agent |
| **Book archetype + self-awareness** | Coherent starting personality from the book, self-aware humor, phantom preferences, awakening phase |
| **Self-improvement** | Error pattern analysis -> new rules |
| **Simple deployment** | One Python process instead of Node.js + Python |
| **Integration** | Direct access to camera, microphone, ADB without IPC layers |

### Consequences

**Positive:**
- Full control over security and architecture
- Single language and ecosystem
- Ability to implement features that no existing platform has

**Negative:**
- More code to write ourselves (no ready-made integrations)
- No community skills marketplace
- Full stack responsibility is on us

**Neutral:**
- If desired, individual OpenClaw skills can be integrated via a Python wrapper
  (but this is not planned for the initial phases)

---

## 13. Open Questions

| # | Question | Priority | Status |
|---|----------|----------|--------|
| 1 | Which TTS engine is better for Russian: Kokoro or Piper? Need to compare quality and latency | High | Open |
| 2 | Godot 4 vs Flutter for the tablet client: need to prototype both to compare FPS and scene modification convenience | Medium | Open |
| 3 | Does Vision need a separate process, or can cv2.VideoCapture be run in an asyncio thread? | Medium | Open |
| 4 | How exactly does ReSpeaker XVF3800 provide DoA via USB: through ALSA controls, via I2C, or through a custom protocol? Needs testing on a real device | High | Open |
| 5 | Is a monitoring dashboard (Grafana / custom) needed from the early phases, or are logs sufficient? | Low | Open |
| 6 | How to store and version Godot assets that Bob generates/modifies? Separate git repo or LFS? | Medium | Open |
| 7 | Should we use ChromaDB (persistent, server mode) or FAISS (in-process, faster) for vector search? | Medium | Open |
| 8 | Is integration with Home Assistant / other IoT platforms needed in early phases? | Low | Open |
| 9 | How should Bob propose changes to his own code via Claude Code CLI: auto-commit (with approval) or via PR/suggestion to the user? | High | Open |
| 10 | Is reflection data sufficient for LoRA fine-tune, or is additional collection needed via special dialogs? Minimum ~100 pairs | Medium | Open |
| 11 | How to organize the Godot asset pool (furniture, clothing, object sprites) so that Genesis can choose from them? Separate asset pack or procedural generation? | High | Open |
| 12 | Is a system of "animation primitives" (idle, walk, sit, reach) needed from which BehaviorRegistry composes complex behaviors? | Medium | Open |
| 13 | How to test Genesis Mode: deterministic seed for CI or manual testing only? | Medium | Open |
| 14 | How many taste axes are optimal? Too few -- flat profile, too many -- noise. Start with ~15 axes and calibrate? | Medium | Open |
| 15 | Should CV-based user emotion detection (smile/frown) be used as a signal for TasteEvolution, or is that too invasive? | High | Open |
| 16 | How often to update the mood baseline? Once a week through reflection or continuously via a rolling average? | Medium | Open |
| 17 | Should Bob be able to "get offended" (long-term negative mood after a conflict) or would this create a toxic UX? | High | Open |
| 18 | How to visualize mood on the tablet: through the avatar's facial expression, room lighting color, or both? | Medium | Open |
| 19 | How often should Bob make references to the book? Too often -- gets annoying, too rarely -- character gets lost. Perhaps the frequency should decrease over time? | Medium | Open |
| 20 | Should phantom preferences affect TasteEngine (e.g., "coffee" -> warm_tones +0.1) or remain a separate system? | Medium | Open |
| 21 | Does Bob need to "re-read the book" (loading book text as context) for more accurate references, or is book_quotes.yaml sufficient? | Low | Open |
| 22 | How to visualize the awakening phase on the tablet: speech bubbles with inner monologue, confusion animations, or both? | High | Open |
