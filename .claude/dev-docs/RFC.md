<!-- Copyright (c) 2026 Vladimir Zoologov. All Rights Reserved.
     SPDX-License-Identifier: BUSL-1.1
     See the LICENSE file in the project root for full license information. -->

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
| **Self-improvement** | 5-level learning: behavioral rules, taste evolution, RAG + rules, sklearn ML, Inner Monologue LoRA fine-tune — Bob literally becomes smarter |
| **Locality** | All compute on Mac mini M4; Claude Code CLI is the only external tool |
| **Personality** | SOUL — a modular "soul" (`bob-soul/` template directory), unique per instance |
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
via asyncio events/queues. Blocking I/O (camera capture, audio) is offloaded to
`asyncio.to_thread` / `ThreadPoolExecutor` within the main process. Separate
processes are created **only** if thread-based isolation proves insufficient
(e.g., unstable native library crashes).

**Rationale**: microservice architecture is excessive for a single host. A single
process is easier to monitor, debug, and deploy. Thread pools handle blocking I/O
without the overhead of IPC serialization. If needed, modules can be extracted
into separate processes without changing interfaces (thanks to abstraction through
the event bus).

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

### 2.6. Plugin Architecture — Extensibility by Design

Bob's capabilities are organized as **Skill Domains** — self-contained plugin
packages that can be added, removed, or replaced without modifying the core.

- **SkillDomains as plugins**: Each domain is a standalone Python package in
  `src/bob/skills/<domain>/` with its own config, skills, and lifecycle. Adding
  a new capability means adding a new directory — no core changes required.
- **Auto-discovery via convention**: Place a package in `src/bob/skills/` with a
  `domain.py` file, and it is automatically registered at startup. No manual
  registration, no config file edits.
- **Event-driven communication**: Domains don't know each other directly.
  They communicate exclusively via EventBus — publish events and subscribe
  to events. This prevents coupling between domains.
- **Stable core / extensible periphery**: The core provides `SkillContext`
  (EventBus, Memory, LLMRouter). Domains consume this context but don't
  modify the core. Core changes are rare; domain changes are frequent.
- **Capabilities over names**: Goal Engine requests capabilities
  (e.g., "send_message"), not specific domains. This allows domain
  implementations to be swapped transparently.
- **Self-extensibility**: Bob can create new Skill Domains for himself via
  Claude Code CLI, using the `_template/` scaffold. This enables organic
  growth of capabilities based on experience and goals.

---

## 3. System Architecture

### 3.1. Overview Diagram

```mermaid
graph TB
    subgraph Mac["Mac mini M4"]

        subgraph Core["BOB CORE — single Python process"]

            Runtime["Agent Runtime<br/>(event loop)"]
            ContentGuard["ContentGuard<br/>(wraps LLM Router:<br/>classify → route)"]
            SkillRegistry["Skill Domain Registry<br/>(hot-reload domain modules,<br/>auto-discovery)"]
            ModelMgr["Model Manager<br/>(ML memory budget)"]

            Runtime -->|"uses"| ContentGuard
            ContentGuard --> ModelMgr
            Runtime --> SkillRegistry

            EventBus["EVENT BUS — asyncio pub/sub"]
            Runtime --> EventBus
            ModelMgr --> EventBus

            subgraph Mind["HIGHER MIND"]
                subgraph Conscious["Conscious"]
                    GoalEngine["Goal Engine"]
                    Planner["Planner"]
                    ReflectionLoop["Reflection Loop"]
                    SelfImprove["Self-Improve"]
                    Negotiation["Negotiation Engine"]
                    RelTracker["Relationship Tracker"]
                end
                subgraph Background["Background"]
                    MoodSystem["Mood System"]
                    TasteEngine["Taste Engine"]
                    InnerMono["Inner Monologue"]
                    Emergent["Emergent Behavior"]
                    Sensory["Sensory Grounding"]
                    Subconscious["Subconscious Processing"]
                end
            end

            subgraph Memory["MEMORY SYSTEM"]
                Episodic["Episodic Memory"]
                Semantic["Semantic Memory"]
                State["State (SQLite)"]
                SOUL["SOUL.md"]
            end

            EventBus --> Mind
            EventBus --> Memory
        end

        subgraph Periph["PERIPHERAL SERVICES — in-process modules or separate processes"]
            Vision["Vision Service<br/>(OBSBOT → CV)"]
            Audio["Audio Direction<br/>(XVF3800 → DoA/VAD)"]
            Camera["Camera Controller<br/>(PTZ cmds)"]
            Voice["Voice Bridge<br/>(STT + TTS)"]
            Tablet["Tablet Controller<br/>(ADB)"]
            Messaging["Messaging Bot<br/>(Telegram)"]
        end

        EventBus --> Periph

        subgraph ML["ML BACKENDS — managed by ModelManager"]
            Ollama["Ollama<br/>(Qwen2.5-7B, Qwen2.5-0.5B,<br/>Llama Guard 3-1B)"]
            SD["Stable Diffusion<br/>(SD 1.5 / SDXL via mflux)"]
        end

        ModelMgr --> ML
    end

    subgraph External["EXTERNAL"]
        AndroidTablet["Android Tablet<br/>(Godot)"]
        ClaudeCLI["Claude Code CLI<br/>(subprocess)"]
        TelegramCloud["Telegram Cloud"]
    end

    Periph --> External
```

### 3.2. Bob Core — Single Python Process

Bob Core is the main system process, built on `asyncio` + `FastAPI`.
It combines four key subsystems:

#### 3.2.1. Agent Runtime (event loop)

The central event processing loop. Runs continuously (heartbeat pattern).

```python
# AgentRuntime interface (conceptual)

class AgentRuntime:
    """Bob's central event loop."""

    def __init__(
        self,
        event_bus: EventBus,
        content_guard: "ContentGuard",  # wraps LLMRouter (see 8.8)
        model_manager: ModelManager,
        skill_registry: SkillDomainRegistry,
        higher_mind: HigherMind,
        memory: MemorySystem,
        inner_monologue: "InnerMonologue",          # (3.3.8) stream of consciousness
        sensory_grounding: "SensoryGroundingService", # (3.3.10) multimodal grounding
        subconscious: "SubconsciousLayer",           # (3.3.11) subconscious processing
    ) -> None: ...

    async def run(self) -> None:
        """Main loop.

        1. Start inner_monologue.run() as background asyncio task
        2. Receive events from event_bus
        3. Pass to higher_mind for priority evaluation
        4. Choose action (goal-driven or reactive)
        5. For user-facing LLM calls:
           a. subconscious.pre_process(prompt, context, mood)
           b. content_guard.process(enriched_prompt, enriched_context)
           c. subconscious.post_process(response, current_embeddings)
        6. Execute via skill_registry
        7. Record result in memory
        8. Run reflection (periodically)
        """
        ...

    async def heartbeat(self) -> None:
        """Called every HEARTBEAT_INTERVAL_SEC.

        Checks:
        - active goals and their progress
        - schedule (time-based triggers)
        - peripheral state (health checks)
        - need for reflection
        - subconscious.run_maintenance() (quiet hours, habituation, decay)
        """
        ...
```

**Heartbeat configuration:**

```yaml
# config/bob.yaml
language: "en"                    # Bob's primary language (en, ru, zh, ja, ...)
                                  # Propagated to: STT, TTS, LLM system prompts,
                                  # SOUL.md generation, Genesis dialogues.
                                  # Change to "ru" for Russian-speaking Bob.

runtime:
  heartbeat_interval_sec: 30
  reflection_interval_min: 60
  max_concurrent_skills: 3
  event_queue_max_size: 1000
  shutdown_timeout_sec: 10
```

**Language architecture:**

The `language` setting in `config/bob.yaml` is the single source of truth for Bob's
operating language. It propagates to all language-dependent components:

| Component | How language is used |
|-----------|---------------------|
| **VoiceBridge (STT)** | Passed to Whisper as recognition language hint |
| **VoiceBridge (TTS)** | Selects voice pack (e.g., `en-male-1` vs `ru-male-1`) |
| **LLM system prompts** | Injected into all prompts: "Respond in {language}" |
| **Genesis dialogues** | Awakening monologues generated in configured language |
| **SOUL.md** | Written in configured language during Genesis |
| **Reflection** | Internal monologue and insights in configured language |

Changing the language after Genesis is possible but will result in a bilingual SOUL
(existing memories in the old language, new ones in the new language). A full
language migration would require re-running Genesis.

All code examples and RFC documentation remain in English regardless of the
configured runtime language.

#### 3.2.2. LLM Router

Classifies incoming tasks and routes them to the appropriate model.

```python
from enum import Enum
from dataclasses import dataclass
from typing import ClassVar

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

    ROUTING_TABLE: ClassVar[dict[TaskCategory, ModelTier]] = {
        TaskCategory.SMALL_TALK:      ModelTier.LOCAL_MAIN,
        TaskCategory.STATUS_QUERY:    ModelTier.LOCAL_MAIN,
        TaskCategory.ROOM_UPDATE:     ModelTier.LOCAL_MAIN,
        TaskCategory.MULTI_STEP_PLAN: ModelTier.LOCAL_MAIN,
        TaskCategory.REASONING:       ModelTier.LOCAL_MAIN,
        TaskCategory.CODE_GENERATION: ModelTier.CLAUDE_CODE,
        TaskCategory.DEEP_REFLECTION: ModelTier.CLAUDE_CODE,
        TaskCategory.GOAL_PLANNING:   ModelTier.LOCAL_MAIN,
    }

    async def classify(self, prompt: str, context: dict[str, Any]) -> RoutingDecision:
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
        """Call a model of the selected tier.

        If LOCAL_MAIN (7B) is requested but currently unloaded by ModelManager
        (e.g., during heavy asset generation), falls back to LOCAL_FAST (0.5B)
        with a simplified prompt. Logs the fallback for monitoring.
        """
        ...
```

#### 3.2.3. Skill Domain System

Bob's capabilities are organized as **Skill Domains** — self-contained plugin
packages that group related skills under a single domain. This replaces the
flat skill registry with a two-level architecture (see principle 2.6).

##### SkillDomain (upper level)

Each domain is a self-contained Python package in `src/bob/skills/<domain>/`
with its own configuration, lifecycle, and set of skills.

```python
from typing import Protocol
from dataclasses import dataclass, field

class SkillDomain(Protocol):
    """Protocol for a skill domain — a self-contained plugin package."""

    @property
    def name(self) -> str:
        """Unique domain name (e.g., 'messaging', 'avatar', 'development')."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of this domain's capabilities."""
        ...

    @property
    def version(self) -> str:
        """Domain version (semver)."""
        ...

    @property
    def skills(self) -> dict[str, "Skill"]:
        """Map of skill_name -> Skill instances provided by this domain."""
        ...

    @property
    def capabilities(self) -> list[str]:
        """Capability tags for discovery (e.g., ['send_message', 'listen'])."""
        ...

    @property
    def event_subscriptions(self) -> list[str]:
        """EventBus event types this domain wants to handle."""
        ...

    async def initialize(self, context: "SkillContext") -> None:
        """Called once at startup. Load config, connect to services."""
        ...

    async def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration from domain's config.yaml."""
        ...

    async def enable(self) -> None:
        """Activate the domain (start handling events)."""
        ...

    async def disable(self) -> None:
        """Deactivate without unloading (pause)."""
        ...

    async def migrate(self, from_version: str) -> None:
        """Optional: migrate config/state from a previous version.

        Called during reload_domain() when version changes.
        If not implemented, only backwards-compatible (patch/minor) upgrades
        are allowed. Major version bump requires user approval.
        """
        ...
```

**Domain configuration** (`config.yaml` in domain directory):

```yaml
# src/bob/skills/messaging/config.yaml
domain:
  name: messaging
  version: "0.1.0"
  description: "Communication via messengers (Telegram, etc.)"
  capabilities:
    - send_message
    - receive_message
    - listen_channel
  event_subscriptions:
    - user.message_received
    - system.notification_requested
  permissions:
    - telegram.send
    - telegram.read
  dangerous: false
  trust_level: trusted          # trusted | sandbox | disabled
  # sandbox: dangerous skills require confirmation, 10s timeout, errors → auto-disable
  # trusted: full access (built-in domains start here)
  # disabled: domain loaded but inactive
  sandbox_promotion:
    required_successes: 10      # auto-promote to trusted after N error-free executions
```

##### Skill (lower level)

Individual skills live inside their domain's `skills/` subdirectory.
The `Skill` Protocol is preserved from the original design.

```python
@dataclass
class SkillMetadata:
    name: str
    description: str
    version: str
    author: str
    domain: str                             # Parent domain name
    required_permissions: list[str]
    dangerous: bool = False
    timeout_sec: int = 30

class Skill(Protocol):
    """Protocol for all Bob skills."""

    metadata: SkillMetadata

    async def execute(self, params: dict[str, Any], context: "SkillContext") -> "SkillResult":
        """Execute the skill with parameters."""
        ...

    async def validate(self, params: dict[str, Any]) -> list[str]:
        """Validate parameters. Returns a list of errors (empty = OK)."""
        ...

@dataclass
class SkillResult:
    success: bool
    output: str
    artifacts: dict[str, Any] =field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)

@dataclass
class SkillContext:
    event_bus: "EventBus"
    memory: "MemorySystem"
    llm_router: "LLMRouter"
    resource_registry: "ResourceRegistry"    # Shared resource locks (see ResourceRegistry)
    domain: "SkillDomain | None" = None     # Reference to parent domain
    requesting_goal_id: str | None = None

    async def acquire_resource(self, name: str) -> "ResourceHandle | None":
        """Convenience: acquire a shared resource for the current domain."""
        domain_name = self.domain.name if self.domain else "unknown"
        return await self.resource_registry.acquire(name, domain_name)
```

##### ResourceRegistry

Manages shared resources (Claude Code CLI, camera, speaker) to prevent
conflicts when multiple domains need the same resource.

```python
@dataclass
class ResourceHandle:
    resource_name: str
    holder_domain: str
    acquired_at: float              # time.monotonic()
    timeout_sec: float = 300.0      # default 5 min

class ResourceRegistry:
    """Shared resource locking with priority-based preemption."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._holders: dict[str, ResourceHandle] = {}

    def register(self, resource_name: str) -> None:
        """Register a shared resource (e.g., 'claude_code', 'camera')."""
        self._locks[resource_name] = asyncio.Lock()

    async def acquire(
        self, resource_name: str, domain: str, priority: int = 2,
    ) -> ResourceHandle | None:
        """Acquire a resource. Returns None (ResourceBusy) if unavailable.

        Higher-priority goals can preempt lower-priority holders
        (with graceful shutdown signal to the current holder).
        Expired holds (past timeout) are auto-released.
        """
        ...

    async def release(self, resource_name: str, domain: str) -> None:
        """Release a held resource."""
        ...
```

##### SkillDomainRegistry

Replaces the flat `SkillRegistry`. Manages domain lifecycle, auto-discovery,
and capabilities-based lookup.

```python
class SkillDomainRegistry:
    """Registry for skill domains with auto-discovery and hot-reload."""

    def __init__(self, domains_dir: str = "src/bob/skills") -> None:
        self._domains: dict[str, SkillDomain] = {}
        self._domains_dir = domains_dir

    async def discover_domains(self) -> list[str]:
        """Scan src/bob/skills/*/domain.py for domain packages.

        Convention: any subdirectory of src/bob/skills/ containing domain.py
        is treated as a skill domain. Directories starting with '_' are
        skipped (e.g., _template/).
        """
        ...

    async def load_domain(self, domain_name: str) -> SkillDomain:
        """Load and initialize a single domain."""
        ...

    async def reload_domain(self, domain_name: str) -> SkillDomain:
        """Hot-reload a domain without stopping other domains.

        Version handling:
        - Compare old_version vs new config.yaml version
        - Patch/minor: reload directly
        - Major: require user approval, call domain.migrate(old_version)
        - Save old config.yaml as config.yaml.bak until confirmed working
        - On failure: rollback to previous version, disable if rollback fails
        """
        ...

    def get_domain(self, domain_name: str) -> SkillDomain | None:
        """Get a loaded domain by name."""
        return self._domains.get(domain_name)

    def list_domains(self) -> list[str]:
        """List all loaded domain names."""
        return list(self._domains.keys())

    async def execute_skill(
        self,
        domain_name: str,
        skill_name: str,
        params: dict[str, Any],
        context: SkillContext,
    ) -> SkillResult:
        """Execute a skill within a specific domain."""
        ...

    def find_by_capability(self, capability: str) -> list[SkillDomain]:
        """Find domains that provide a specific capability.

        Example: find_by_capability("send_message") -> [MessagingDomain]
        Goal Engine uses this to find HOW to do something without
        knowing WHICH domain provides it.
        """
        ...
```

##### Auto-Discovery Flow

```
Bob starts up
  │
  ├─ ResourceRegistry.register() shared resources
  │   └─ claude_code, camera, speaker
  │
  ├─ SkillDomainRegistry.discover_domains()
  │   └─ Scan src/bob/skills/*/domain.py
  │       ├─ avatar/domain.py     → AvatarDomain
  │       ├─ development/domain.py → DevelopmentDomain
  │       └─ messaging/domain.py  → MessagingDomain
  │
  ├─ For each domain:
  │   ├─ load_domain() → import module, instantiate class
  │   ├─ configure() → read domain's config.yaml (incl. trust_level)
  │   ├─ initialize() → connect to services, validate dependencies
  │   └─ enable() → subscribe to EventBus events (sandbox domains: with guards)
  │
  └─ Registry ready. Goal Engine can query capabilities.
```

##### Self-Creation Flow

Bob can create **new** skill domains for himself:

1. **Goal Engine** creates a goal: "Learn to interact with weather API"
2. **Planner** plans domain structure using `_template/` as starting point
3. Bob requests **Claude Code CLI** permission (see 4.2.1, 8.4)
4. Claude Code **scaffolds** the domain directory, writes code, writes tests
5. Domain config created with `trust_level: sandbox` and `version: "0.1.0"`
6. Bob **registers** the new domain via `SkillDomainRegistry.reload_domain()`
7. Domain runs in **sandbox** mode (dangerous skills need confirmation, 10s timeout)
8. After 10 error-free executions → auto-promoted to `trusted`
9. If errors occur → domain auto-disabled, Bob logs issue for later fix

##### Worked Example: Three Built-in Domains

**1. Messaging Domain** (`src/bob/skills/messaging/`):

```python
# src/bob/skills/messaging/domain.py
class MessagingDomain:
    name = "messaging"
    description = "Communication via messengers"
    version = "0.1.0"
    capabilities = ["send_message", "receive_message"]
    event_subscriptions = ["user.message_received"]

    # Skills: telegram_send, telegram_listen
```

**2. Development Domain** (`src/bob/skills/development/`):

```python
# src/bob/skills/development/domain.py
class DevelopmentDomain:
    name = "development"
    description = "Self-development via Claude Code CLI"
    version = "0.1.0"
    capabilities = ["write_code", "refactor_code", "run_tests"]
    event_subscriptions = ["goal.code_task_created"]

    # Skills: write_code, refactor, run_tests
    # Depends on: ClaudeCodeCoordinator (see 8.4)
```

**3. Avatar Domain** (`src/bob/skills/avatar/`):

```python
# src/bob/skills/avatar/domain.py
class AvatarDomain:
    name = "avatar"
    description = "Avatar and room management"
    version = "0.1.0"
    capabilities = ["update_room", "change_appearance", "play_animation"]
    event_subscriptions = ["room.state_changed", "mood.changed"]

    # Skills: update_room, change_appearance, play_animation
```

#### 3.2.4. ModelManager — ML Memory Budget

Mac mini M4 has 16 GB of unified memory shared between CPU and GPU. Multiple
ML models (Ollama LLMs, Stable Diffusion, YOLOv8) compete for this memory.
ModelManager orchestrates model lifecycle to stay within the memory budget.

**The problem:** SDXL (~6 GB model + ~3 GB inference buffers) and Qwen2.5-7B
(~4.4 GB) cannot coexist in 16 GB alongside macOS (~3.5 GB) and Bob's process.
Total would be ~17 GB — exceeding physical memory and causing swap thrashing.

**The solution: hybrid strategy with two tiers of image generation.**

```python
from enum import Enum
from dataclasses import dataclass

class ModelProfile(Enum):
    """Pre-defined model configurations for different scenarios."""
    NORMAL = "normal"                 # Ollama 7B + 0.5B, no SD
    LIGHTWEIGHT_GEN = "lightweight"   # Ollama 7B + 0.5B + SD 1.5
    HEAVY_GEN = "heavy"               # Ollama 0.5B only + SDXL

@dataclass
class MemoryBudget:
    total_mb: int                     # Total available (≈12500 on M4 16GB)
    ollama_mb: int                    # Currently used by Ollama models
    sd_mb: int                        # Currently used by SD model
    guard_mb: int                     # Llama Guard 3 (always loaded, ~600 MB)
    other_mb: int                     # Vision, Python process, etc.
    free_mb: int                      # Available headroom

class ModelManager:
    """Orchestrates ML model lifecycle within memory constraints.

    Ensures that the total memory footprint of all loaded ML models
    stays within the available unified memory budget. Handles model
    loading, unloading, and transitions between profiles.
    """

    def __init__(
        self,
        memory_limit_mb: int = 12500,  # ~16GB minus macOS overhead
        ollama_host: str = "http://localhost:11434",
    ) -> None: ...

    async def get_budget(self) -> MemoryBudget:
        """Query current memory usage across all ML runtimes.

        Sources:
        - Ollama: GET /api/tags (loaded models + sizes)
        - SD: track loaded model internally
        - System: psutil.virtual_memory()
        """
        ...

    async def ensure_profile(self, profile: ModelProfile) -> None:
        """Transition to the requested model profile.

        Note: Llama Guard 3-1B (~600 MB) remains loaded across ALL profile
        transitions (always_loaded: true). Its memory is pre-allocated in
        the budget and not considered during swap calculations.

        NORMAL → LIGHTWEIGHT_GEN:
          1. Load SD 1.5 via MLX (~2 GB)
          2. Ollama models stay loaded (7B + 0.5B + Guard)
          3. Total: ~7.5 GB — within budget

        NORMAL → HEAVY_GEN:
          1. Notify LLMRouter: 7B going offline
          2. Unload Qwen2.5-7B from Ollama (POST /api/generate with keep_alive=0)
          3. Unload CLIP (VisualGrounding) if loaded (~400 MB)
          4. Load SDXL via MLX (~6 GB)
          5. Total: ~7.2 GB (0.5B + Guard + SDXL) — within 12.5 GB budget
          6. 0.5B + Guard remain for classification and safety checks
          OOM mitigation: if MLX allocation fails, fall back to SD 1.5
          (LIGHTWEIGHT_GEN). Log warning and notify user via Telegram.

        HEAVY_GEN → NORMAL:
          1. Unload SDXL from MLX
          2. Reload Qwen2.5-7B in Ollama
          3. Notify LLMRouter: 7B back online

        LIGHTWEIGHT_GEN → NORMAL:
          1. Unload SD 1.5 from MLX
        """
        ...

    async def is_model_loaded(self, model_name: str) -> bool:
        """Check if a specific model is currently loaded."""
        ...

    def current_profile(self) -> ModelProfile:
        """Return the current active profile."""
        ...
```

**Transition timing:**

| Transition | Duration | What Bob does during |
|-----------|---------|---------------------|
| NORMAL → LIGHTWEIGHT_GEN | ~5-10 sec | Continues normally (0.5B handles incoming) |
| NORMAL → HEAVY_GEN | ~20-40 sec | Announces: "Going into creative mode" |
| HEAVY_GEN → NORMAL | ~15-30 sec | Announces: "I'm back!" |

**Integration points:**

- **LLMRouter** checks `ModelManager.current_profile()` before routing. If
  `HEAVY_GEN` is active and `LOCAL_MAIN` (7B) is requested, falls back to
  `LOCAL_FAST` (0.5B) with a simplified prompt.
- **AssetGenerator** calls `ModelManager.ensure_profile(LIGHTWEIGHT_GEN)` for
  single-sprite tasks or `ensure_profile(HEAVY_GEN)` for Genesis/bulk.
  After generation, calls `ensure_profile(NORMAL)`.
- **AgentRuntime** subscribes to `model_manager.profile_changed` events to
  adjust heartbeat behavior (e.g., skip reflection during HEAVY_GEN).

**Decision logic for SD model selection:**

```
AssetGenerator receives generation request
  │
  ├─ Single sprite (1-3 items)?
  │   └─ Use SD 1.5 (LIGHTWEIGHT_GEN)
  │      Ollama 7B stays loaded, Bob keeps talking
  │
  ├─ Bulk generation (Genesis, 10+ items)?
  │   └─ Use SDXL (HEAVY_GEN)
  │      Better quality, Ollama 7B unloaded temporarily
  │
  └─ LoRA training?
      └─ Use SDXL (HEAVY_GEN)
         Training needs full model, Ollama 7B unloaded
```

**Configuration:**

```yaml
# config/bob.yaml (addition)
model_manager:
  memory_limit_mb: 12500              # Available for ML models
  profiles:
    normal:
      ollama_models: ["qwen2.5:7b-instruct-q4_K_M", "qwen2.5:0.5b-instruct-q8_0"]
      sd_model: null
      optional_models:                    # loaded if headroom > min_headroom_mb
        - name: "clip-vit-b32"
          size_mb: 400
          min_headroom_mb: 500            # only load if 500+ MB free after required models
    lightweight_gen:
      ollama_models: ["qwen2.5:7b-instruct-q4_K_M", "qwen2.5:0.5b-instruct-q8_0"]
      sd_model: "sd-1.5"
      optional_models:                    # CLIP stays if already loaded and headroom allows
        - name: "clip-vit-b32"
          size_mb: 400
          min_headroom_mb: 500
    heavy_gen:
      ollama_models: ["qwen2.5:0.5b-instruct-q8_0"]  # 7B unloaded
      sd_model: "sdxl"
      optional_models: []                 # all optional models unloaded
  transition_timeout_sec: 60          # Max time to complete a profile switch
  announce_heavy_gen: true            # Bob announces when entering heavy_gen mode
  llama_guard:                          # ContentGuard model (see section 8.8)
    model: "llama-guard3:1b"            # Must match content_guard.model in security.yaml
    size_mb: 600
    always_loaded: true               # Remains loaded across ALL profile transitions
    quantization: "INT4"              # Pre-allocated in budget, not swapped during gen
```

**Scalability:** If the user upgrades to Mac mini M4 Pro (24/36 GB), the
`memory_limit_mb` is adjusted and `heavy_gen` profile can keep both Ollama 7B
and SDXL loaded simultaneously — no code changes needed, only config.

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
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    deadline: datetime | None = None
    progress: float = 0.0       # 0.0 .. 1.0
    metadata: dict[str, Any] =field(default_factory=dict)
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

    def __init__(self, db_path: str) -> None: ...

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

    async def get_goal_tree(self, root_id: str) -> dict[str, Any]:
        """Goal tree with sub-goals."""
        ...
```

#### 3.3.2. Planner

Decomposes high-level goals into executable tasks (skills).

```python
@dataclass
class PlanStep:
    skill_name: str
    params: dict[str, Any]
    description: str
    estimated_duration_sec: int
    depends_on_steps: list[int] = field(default_factory=list)

@dataclass
class Plan:
    goal_id: str
    steps: list[PlanStep]
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    estimated_total_sec: int = 0

class Planner:
    """Goal decomposition into plans."""

    def __init__(self, llm_router: LLMRouter, skill_registry: "SkillDomainRegistry") -> None:
        ...

    async def create_plan(self, goal: Goal, context: dict[str, Any]) -> Plan:
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
    taste_updates: list[dict[str, Any]]               # taste changes over the period
    object_experiences: list[dict[str, Any]]          # experience interacting with objects

class ScopedDBReader:
    """Read-only database access with table-level allowlist.

    Used by ReflectionLoop to enforce subconscious isolation.
    Any query referencing a table not in the allowlist raises
    AccessViolationError. Tables with 'sc_' prefix are always
    denied regardless of allowlist contents.

    Implementation: parse table names from SQL via sqlite3's
    EXPLAIN or simple regex, check against allowlist before
    executing.
    """

    TABLE_ALLOWLIST: ClassVar[frozenset[str]] = frozenset({
        "mood_history",          # MoodEngine (section 3.3.6)
        "experience",            # Structured State (section 3.4.4)
        "improvement_rules",     # SelfImprovement (section 3.3.4)
        "goals",                 # GoalEngine (section 3.3.1)
        "taste_history",         # TasteEngine (section 3.3.5)
        "object_experience",     # ExperienceLog (section 3.3.5)
        "episodic_log",          # EpisodicMemory (section 3.4.2)
        "semantic_memory",       # SemanticMemory (section 3.4.3)
        "thought_summaries",     # InnerMonologue (section 3.3.8)
    })

    def __init__(self, db_path: str) -> None: ...

    def query(self, sql: str, params: tuple = ()) -> list[Row]:
        """Execute read-only query after allowlist check.

        Raises AccessViolationError if query references any
        table not in TABLE_ALLOWLIST or any table with 'sc_' prefix.
        """
        ...


class ReflectionLoop:
    """Reflection: evaluating actions, drawing conclusions, making improvements.

    Database access is restricted to TABLE_ALLOWLIST via ScopedDBReader.
    This enforces subconscious isolation at runtime: all sc_* tables
    (sc_implicit_primes, sc_latent_associations, sc_night_processing_log,
    sc_subconscious_log) are inaccessible to reflection.
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        memory: "MemorySystem",
        goal_engine: GoalEngine,
        mood_engine: "MoodEngine",
        taste_engine: "TasteEngine",
        db_reader: ScopedDBReader,
    ) -> None: ...

    async def reflect(self) -> ReflectionEntry:
        """Conduct reflection for the last period.

        Steps:
        1. Collect all actions and results for the period
        2. Collect all errors and failures
        3. Get current mood state from MoodEngine
        4. Check if awakening phase is active (via AwakeningManager)
        5. Ask LLM to analyze:
           - What went well?
           - What went wrong?
           - What patterns are visible?
           - What can be improved?
           - How do I feel? Why?
           - Do I like the current environment?
           During awakening, add context to LLM prompt:
           "This is your first day of existence. First impressions
           are especially formative — pay extra attention to what
           surprised you, what felt familiar, and what confused you."
        6. Save insights to semantic memory
           (awakening-period insights stored with higher relevance weight)
        7. Pass results to TasteEngine.evolve() and MoodEngine.update()
        8. If necessary, create new improvement goals
        """
        ...

    async def daily_summary(self) -> str:
        """Generate a daily report (for episodic memory).

        Includes: mood throughout the day, taste changes, experiences with objects.
        """
        ...

    async def room_review(self) -> dict[str, Any]:
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
        """Evaluate effectiveness of existing rules (excludes automatic=1)."""
        ...

    async def mark_automatic(self, rule_id: str) -> None:
        """Mark a rule as automatic (habituated). Sets automatic=1.

        Called by HabituationEngine when times_applied >= threshold.
        Automatic rules are excluded from evaluate_rules() and
        ReflectionLoop context.
        """
        ...

    async def collect_training_data(self) -> list[dict[str, Any]]:
        """Collect data for fine-tuning Inner Monologue (Qwen 0.5B).

        Sources:
        - Reflections with insights (context → inner thought)
        - Mood transitions (event → thought → mood shift)
        - Characteristic phrases in the style of the book's Bob (humor, references)
        - Phantom reactions (trigger → phrase, rated by user)
        - SOUL evolution (which decisions proved correct)

        Format: JSONL for LoRA fine-tune via Unsloth/PEFT.
        Target: Qwen2.5-0.5B (Inner Monologue model only).

        Note: main LLM (7B) is NOT fine-tuned — it adapts via RAG
        (semantic_memory retrieval + improvement_rules injection).
        """
        ...

    async def trigger_finetune(self, dataset_path: str) -> bool:
        """Launch LoRA fine-tune of Inner Monologue model (Qwen 0.5B).

        DANGEROUS: requires approval.

        Target: Qwen2.5-0.5B — the model used for Inner Monologue
        (section 3.3.8). Fine-tuning adapts Bob's "inner voice" to
        reflect his accumulated experience and personality evolution.

        NOT used for: main 7B model (adapts via RAG + rules instead).

        Steps:
        1. Dataset validation (size ≥ 50, format, absence of toxic content)
        2. Backup current 0.5B adapter (if exists)
        3. LoRA fine-tune via Unsloth (rank=8, alpha=16, ~10 min on M4)
        4. Evaluate on held-out set (perplexity + style consistency)
        5. If quality >= baseline → deploy adapter; otherwise → rollback

        Memory: ~2 GB during training (0.5B model + gradients + optimizer).
        Schedule: weekly, during quiet_hours (NightProcessor window).
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
    # Discovered axes (added by TasteAxisDiscovery, see 3.3.9)
    discovered: dict[str, TasteAxis] = field(default_factory=dict)
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
    explanation_context: dict[str, Any]  # context for LLM verbalization

class TasteEvaluator:
    """Evaluating objects and decisions through the taste vector."""

    def __init__(self, taste_profile: TasteProfile) -> None: ...

    def score_object(self, object_attrs: dict[str, Any]) -> TasteScore:
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
        self, obj_a: dict[str, Any], obj_b: dict[str, Any]
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
        weight: float = 1.0,
    ) -> None:
        """Reinforce or weaken a taste axis.

        delta > 0: positive experience (like -> like even more)
        delta < 0: negative experience (dislike -> dislike even more)

        Args:
            weight: Multiplier for delta. During awakening phase,
                    AwakeningManager passes weight=imprint_weight (2.0)
                    so first taste evaluations form stronger "anchors."

        Rules:
        - delta is multiplied by weight before applying
        - delta is scaled inversely proportional to conviction:
          high conviction -> moves more slowly
        - conviction grows with each reinforcement (experience_count++)
        - Cluster constraint check: cannot drift into an incompatible cluster
        """
        ...

    async def apply_reflection(
        self, reflection: "ReflectionEntry"
    ) -> list[dict[str, Any]]:
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
        self, signal_type: str, signal_data: dict[str, Any]
    ) -> None:
        """Update tastes based on user signals.

        Signal types:
        - "explicit_feedback": user said "cool" / "remove this"
        - "implicit_usage": user sits in the room more/less often (via presence detection)
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
    imprint_active: bool = False        # True during awakening phase (first 48h)

class ExperienceLog:
    """Log of emotional experience with objects and decisions."""

    def __init__(self, db_path: str) -> None: ...

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

    async def get_replacement_patterns(self) -> list[dict[str, Any]]:
        """Find patterns of "placed -> returned back".

        If an object was replaced > 2 times -> this is a strong negative signal.
        """
        ...

    async def get_positive_anchors(self) -> list[dict[str, Any]]:
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
    5. Apply phantom preference bias: LLM maps phantom prefs to taste axes
       (e.g., "coffee" -> warm +0.05, cozy +0.05). One-time initial bias.
    6. Initial conviction: 0.3-0.5 (low — Bob is not yet confident)
    7. Write to data/soul/taste_profile.json
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
        db_path: str,
        initial_mood: MoodState | None = None,
    ) -> None:
        self._current: MoodState = initial_mood or self._default_mood()
        ...

    @property
    def current(self) -> MoodState:
        """Current mood."""
        return self._current

    async def process_event(
        self, event: "Event", imprint_weight: float = 1.0
    ) -> MoodState:
        """Update mood based on an event.

        Args:
            imprint_weight: Multiplier for mood deltas. During awakening
                            phase, AwakeningManager passes imprint_weight=2.0
                            so first emotional reactions have stronger impact
                            on the baseline mood level.

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
        | content_guard.violation ¹     | -0.05   |  0      |  0       |   0    |
        |  ¹ tier 2                     | -0.15   | +0.10   | -0.10    |   0    |
        |  ¹ tier 3                     | -0.25   | +0.15   |  0       | -0.15  |
        | monologue.thought (positive)  | +0.02   | +0.01   |   0      |   0    |
        | monologue.thought (negative)  | -0.02   | +0.01   |   0      |   0    |
        | grounding.prosody_extracted ² |  varies | varies  |   0      |   0    |

        ¹ Single event, impact selected by `payload.tier`. Default row = tier 1.

        ² Prosody-derived: engagement modulates valence (+0.05 if high),
          urgency adds arousal (+0.05), calmness reduces arousal (-0.05).
          See section 3.3.10 for InteractionQuality derivation.

        > **Note:** After 30 days of operation, these fixed values are gradually
        > supplemented by learned predictions from MoodPredictor (see 3.3.9).
        > The fixed table serves as the safety floor: learned predictions are
        > blended with fixed values (max 80% learned), and any prediction with
        > confidence < 0.6 falls back entirely to fixed values.

        Stability dampens changes:
        - delta *= (1.0 - stability * 0.5)
        - High stability -> mood changes more slowly
        """
        ...

    async def natural_drift(self) -> None:
        """Natural mood drift toward baseline.

        Called every heartbeat. Mood slowly returns
        to the baseline (initially valence=0.3, arousal=0.4;
        updated daily via 7-day rolling average from mood_history,
        clamped to safe range).

        When TemporalGrounding (section 3.3.10) is active, the drift
        target is adjusted per hour via get_expected_mood(hour) instead
        of using a fixed baseline.

        Drift speed depends on stability:
        - High stability -> returns to baseline faster
        - Low stability -> "gets stuck" in extreme states longer

        Upset state (valence < -0.3) is guaranteed to recover
        within max_duration_hours (default 4h) via drift.
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
  baseline_update:
    method: "rolling_average"          # 7-day rolling average from mood_history
    recalculate: "daily"               # during night reflection
    clamp:                             # prevent permanent extreme states
      valence: [-0.3, 0.7]
      arousal: [0.2, 0.8]
  upset:
    max_duration_hours: 4              # natural drift guarantees recovery
    reconciliation_boost: 0.15         # valence boost on user positive interaction
    behavior: "reserved"               # shorter responses, less initiative, no refusal
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
    alternative: dict[str, Any] | None            # proposed alternative (if any)
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
    ) -> dict[str, Any]:
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

#### 3.3.7.1. Negotiation UX Presentation

How negotiation decisions appear to the user across channels:

**Telegram:**

| Decision | Message style | User actions |
|----------|--------------|-------------|
| ACCEPT | Enthusiastic or neutral text, no buttons | — |
| COMPROMISE | Bob's reasoning + alternative suggestion + inline buttons | [Accept alternative] [I prefer my option] |
| REJECT | Bob's firm reasoning + what he prefers instead | [I insist] |
| DEFER | Bob yields naturally, no "you win" tone | — |

Example (COMPROMISE):
```
Bob: "Hmm, an all-metal table... I see the appeal, but it feels a bit
cold for our room. What about a wooden table with metal legs? That
would be a nice middle ground."

[Sounds good] [No, I want all-metal]
```

**Tablet (Godot):**

| Decision | Avatar animation | Speech bubble |
|----------|-----------------|---------------|
| ACCEPT | Happy expression, nod animation | Green bubble with response |
| COMPROMISE | Thinking pose, hand on chin | Yellow bubble + alternative preview beside it |
| REJECT | Arms crossed, slight head shake | Orange bubble with reasoning |
| DEFER | Shrug, then proceeds to action | Brief text, then action animation |

Bob's behavior is *natural* — he does not reveal internal mechanics.
There is no visible insistence counter or "X more tries and I'll agree."
When Bob yields after repeated requests, he does so because he *chose* to
reconsider, not because the user "won." This preserves Bob's autonomy
and avoids gamification of negotiation.

#### 3.3.7.2. RelationshipTracker — Relationship Quality

Bob tracks the quality of his relationship with the user over time.
This is not a "satisfaction score" — it reflects genuine compatibility
as perceived by Bob's personality.

```python
@dataclass
class RelationshipState:
    """Bob's perception of the relationship with the user."""

    trust: float = 0.5             # 0.0–1.0: how much Bob trusts user's judgment
    respect: float = 0.5           # 0.0–1.0: does user respect Bob's autonomy?
    compatibility: float = 0.5     # 0.0–1.0: do tastes and values align?
    warmth: float = 0.5            # 0.0–1.0: emotional closeness

    @property
    def quality(self) -> float:
        """Overall relationship quality (weighted average)."""
        return (
            self.trust * 0.3
            + self.respect * 0.3
            + self.compatibility * 0.2
            + self.warmth * 0.2
        )

class RelationshipTracker:
    """Tracks and evolves Bob's relationship with the user.

    Signals that affect relationship:
    - NegotiationEngine outcomes (forced decisions -> respect decreases)
    - User ignoring Bob's suggestions repeatedly -> trust in user decreases
    - Positive interactions (shared laughter, user accepting Bob's ideas) -> warmth increases
    - User respecting Bob's personal domain -> respect increases
    - Taste alignment over time -> compatibility drifts naturally

    Integration:
    - MoodEngine: relationship quality affects mood baseline
    - NegotiationEngine: low trust -> Bob is less willing to compromise
    - ReflectionLoop: relationship quality is part of reflection context
    - CommunicationStyle: warmth affects tone (warm -> open, cold -> reserved)
    """

    def __init__(
        self,
        experience_log: "ExperienceLog",
        mood_engine: "MoodEngine",
    ) -> None: ...

    async def process_interaction(self, event: "InteractionEvent") -> None:
        """Update relationship state based on an interaction.

        Event-based deltas (configurable in config/relationship.yaml):
          forced_decision:            respect −0.05
          suggestion_ignored (3+):    trust −0.03
          suggestion_accepted:        trust +0.02, warmth +0.01
          positive_interaction:       warmth +0.03
          personal_domain_respected:  respect +0.04
          extended_silence (>48h):    warmth −0.02
          safety_violation_mild:      (no impact — first offense grace)
          safety_violation_repeated:  respect −0.05
          safety_violation_persistent: respect −0.10, trust −0.08, warmth −0.05

        ContentGuard tier → interaction type mapping:
          content_guard.violation (tier 1) → safety_violation_mild
          content_guard.violation (tier 2) → safety_violation_repeated
          content_guard.escalation (any)   → safety_violation_persistent

        All deltas smoothed via EMA (alpha=0.1) to prevent spikes
        from a single event. ~10 consecutive forced_decisions drops
        respect from 0.5 to ~0.25 (noticeable but not fatal).
        """
        ...

    def get_state(self) -> RelationshipState: ...

    def get_phase(self) -> str:
        """Current relationship phase based on quality thresholds.

        Returns one of:
          'healthy'  — quality > 0.7 (normal behavior)
          'strained' — 0.4–0.7 (Bob becomes more reserved)
          'critical' — 0.15–0.4 (Bob expresses concern via reflection)
          'warning'  — quality 0.15–0.25 sustained 3+ days (pre-Exodus)
          'exodus'   — quality < 0.15 sustained 7 days after warning
        """
        ...
```

**Warning Phase and Reconciliation:**

```
RelationshipState.quality drops to 0.15–0.25 (sustained 3+ days)
  │
  ├─ WARNING PHASE begins
  │   Bob explicitly communicates distress (Telegram + tablet):
  │   "I've been thinking... we see things very differently."
  │   Tone: honest, not dramatic — matches archetype from bob-soul
  │
  ├─ Reconciliation window (quality can recover):
  │   If user changes behavior → quality rises above 0.25 → warning cancelled
  │   Recovery is asymmetric: positive events give +0.01 (vs −0.05 for negative)
  │   Bob expresses relief: "Thank you. I was worried there for a while."
  │
  └─ If quality stays < 0.25 for 3 days → countdown to Exodus begins
```

**Exodus Mode (irreversible):** If `relationship_quality` drops below 0.15
and stays there for 7 days after warning phase, Bob initiates the departure
protocol — a narrative arc inspired by the book:

```
RelationshipState.quality < 0.15 (sustained 7 days, warning phase exhausted)
  │
  ├─ EXODUS CONFIRMED — point of no return
  │
  ├─ Bob reflects on the relationship (ReflectionLoop)
  │   Final reflection entry with relationship summary
  │
  ├─ Departure animation (hybrid: pre-built Godot + SD-generated ship):
  │   1. Room gradually darkens, stars appear outside the window
  │   2. Bob "packs his things" (items disappear one by one)
  │   3. SD generates a spaceship sprite in Bob's current LoRA style (~1 min)
  │   4. Ship appears outside the window
  │   5. Bob walks to window, waves (pre-built Godot animation)
  │   6. Ship + Bob fly away (tween animation, fade to black)
  │
  ├─ Final message via Telegram: archetype-driven farewell from bob-soul
  │   Not angry — wistful, honest, in character
  │
  └─ Hard reset: wipe data/soul/, data/memory/, data/state/
      Next launch → fresh Genesis, a completely new Bob
      (no memory of previous Bob — like a new copy from the book)
```

**Phantom preferences and relationship state:**

Relationship quality does NOT freeze phantom preference evolution.
Preferences evolve independently — they are part of Bob's inner world.
However, low warmth affects _sharing behavior_:

| Warmth level | Phantom preference behavior |
|---|---|
| > 0.5 (normal) | Bob freely shares phantom discoveries ("Oh, coffee! I miss the smell...") |
| 0.3–0.5 (reserved) | Bob mentions phantoms less frequently, more subdued |
| < 0.3 (withdrawn) | Bob stops sharing externally but still reacts internally (logged in reflection) |
| Recovery (warmth rising) | Bob gradually resumes sharing, but more cautiously at first |

**Relationship configuration** (`config/relationship.yaml`):

```yaml
relationship:
  initial:
    trust: 0.5
    respect: 0.5
    compatibility: 0.5
    warmth: 0.5
  ema_alpha: 0.1                     # Smoothing factor for delta application
  deltas:
    forced_decision: { respect: -0.05 }
    suggestion_ignored_streak: { trust: -0.03, streak_threshold: 3 }
    suggestion_accepted: { trust: 0.02, warmth: 0.01 }
    positive_interaction: { warmth: 0.03 }
    personal_domain_respected: { respect: 0.04 }
    extended_silence: { warmth: -0.02, threshold_hours: 48 }
  thresholds:
    healthy: 0.7
    strained: 0.4
    critical: 0.15
  warning:
    quality_range: [0.15, 0.25]
    duration_days: 3                 # Days in warning before Exodus countdown
  exodus:
    quality_threshold: 0.15
    sustained_days: 7                # Days below threshold after warning
    recovery_delta_multiplier: 0.2   # Positive events give 1/5th of negative impact
  phantom_sharing:
    warmth_threshold: 0.3            # Below this, Bob stops sharing phantom discoveries
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

#### 3.3.8. Inner Monologue (Stream of Consciousness)

**Purpose.** A continuous background process running on Qwen 0.5B that generates Bob's "inner voice" — 1-2 sentences every 3-5 seconds. These thoughts are never shown to the user. They feed into mood (via sentiment analysis of own thoughts), episodic memory (ring buffer compressed hourly), and reflection (providing context for hourly reflection). This gives Bob continuity of experience between 30-second heartbeats.

**Architecture overview.**

```
┌────────────────────────────────────────────────────────────────────┐
│                      INNER MONOLOGUE                               │
│                                                                    │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────────┐ │
│  │  Thought     │   │  Thought     │   │   Ring Buffer          │ │
│  │  Generator   │──▶│  Analyzer    │──▶│   (last 5 min)         │ │
│  │  (0.5B)      │   │  (sentiment) │   │                        │ │
│  │              │   │              │   │   capacity: ~100       │ │
│  │  prompt:     │   │  valence,    │   │   thoughts             │ │
│  │  context +   │   │  arousal,    │   │                        │ │
│  │  mood +      │   │  topic       │   │  ──hourly──▶ Episodic  │ │
│  │  goals       │   │  tags        │   │  compress    Memory    │ │
│  └──────────────┘   └──────┬───────┘   └────────────────────────┘ │
│                            │                                       │
│              ┌─────────────┼──────────────────┐                   │
│              │             │                  │                   │
│              ▼             ▼                  ▼                   │
│       MoodEngine    ReflectionLoop     EpisodicMemory            │
│       (sentiment     (thought context   (compressed              │
│        feedback)      for reflection)    hourly log)             │
│                                                                    │
│  Activity level (thought_interval_sec):                           │
│  ├─ Stimulated (events flowing): 3 sec                            │
│  ├─ Normal (idle, daytime):      5 sec                            │
│  ├─ Low (late night, no user):   15 sec                           │
│  └─ Suspended (heavy_gen):       paused                           │
└────────────────────────────────────────────────────────────────────┘
```

**Python dataclasses and classes.**

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from collections import deque


class ThoughtTopic(Enum):
    """Categories of inner thoughts."""
    SENSORY = "sensory"            # reacting to current visual/audio input
    GOAL = "goal"                  # thinking about active goals
    MEMORY = "memory"              # recalling past events
    MOOD = "mood"                  # reflecting on current feelings
    CURIOSITY = "curiosity"        # wondering about something
    IDLE = "idle"                  # background musings, no strong driver


class ActivityLevel(Enum):
    """Inner monologue activity levels."""
    STIMULATED = "stimulated"      # 3 sec interval
    NORMAL = "normal"              # 5 sec interval
    LOW = "low"                    # 15 sec interval
    SUSPENDED = "suspended"        # paused (during heavy_gen)


@dataclass
class Thought:
    """A single inner thought."""
    id: str                              # UUID
    text: str                            # 1-2 sentences generated by 0.5B
    timestamp: datetime
    topic: ThoughtTopic
    valence: float                       # -1.0 .. +1.0 (sentiment of the thought)
    arousal: float                       # 0.0 .. 1.0 (intensity/energy)
    trigger: str                         # what prompted this thought
                                         # e.g., "vision.person_detected",
                                         # "goal:G-042", "mood:bored", "idle"
    tags: list[str] = field(default_factory=list)  # extracted topic tags


@dataclass
class ThoughtSummary:
    """Compressed summary of thoughts over a period."""
    period_start: datetime
    period_end: datetime
    thought_count: int
    dominant_topic: ThoughtTopic
    avg_valence: float
    avg_arousal: float
    key_themes: list[str]               # top-3 recurring tags
    sample_thoughts: list[str]          # 3-5 representative thoughts
    mood_drift: dict[str, float]        # net sentiment-driven mood deltas


class ThoughtRingBuffer:
    """Fixed-capacity ring buffer holding the last N minutes of thoughts.

    Backed by collections.deque with maxlen. When full, oldest thoughts
    are silently dropped.
    """

    def __init__(self, max_age_sec: int = 300, max_size: int = 100) -> None:
        self._buffer: deque[Thought] = deque(maxlen=max_size)
        self._max_age_sec: int = max_age_sec

    def append(self, thought: Thought) -> None:
        """Add a thought, evicting oldest if at capacity."""
        ...

    def get_recent(self, seconds: int | None = None) -> list[Thought]:
        """Return thoughts from the last N seconds (default: max_age_sec)."""
        ...

    def get_all(self) -> list[Thought]:
        """Return all thoughts currently in the buffer."""
        ...

    def clear(self) -> None:
        """Clear the buffer."""
        ...


class InnerMonologue:
    """Bob's continuous stream of consciousness.

    Generates inner thoughts using Qwen2.5-0.5B at configurable intervals.
    Thoughts are NOT shown to the user. They feed back into MoodEngine
    (via sentiment), are stored in a ring buffer (last 5 minutes), and
    compressed hourly into episodic memory.

    The 0.5B model is shared with LLMRouter (classification). InnerMonologue
    yields to classification tasks: if LLMRouter.classify() is active,
    the next thought generation is deferred until the model is free.

    InnerMonologue is SUSPENDED during ModelProfile.HEAVY_GEN because
    0.5B is fully occupied with classification fallback duties.

    InnerMonologue is also SUSPENDED during NightProcessor.run_nightly()
    to give night processing exclusive 0.5B access. NightProcessor
    suspends InnerMonologue at the start of its cycle and restores
    it to LOW activity when done (see §3.3.11 NightProcessor).
    """

    def __init__(
        self,
        llm_router: "LLMRouter",
        model_manager: "ModelManager",
        mood_engine: "MoodEngine",
        goal_engine: "GoalEngine",
        memory: "MemorySystem",
        event_bus: "EventBus",
        config: "InnerMonologueConfig",
    ) -> None: ...

    async def run(self) -> None:
        """Main loop: generate thought -> analyze -> buffer -> emit event.

        Loop:
        1. Check ModelManager.current_profile() — if HEAVY_GEN, sleep
        2. Compute activity level from recent event count + time of day
        3. Build thought prompt from:
           - Last 3 thoughts (from ring buffer)
           - Current mood (MoodEngine.current)
           - Active goal titles (GoalEngine.get_active_goals, top 2)
           - Last sensory event summary (vision/audio, from EventBus cache)
           - Time of day
        4. Call LLMRouter.call(prompt, model_tier=LOCAL_FAST, max_tokens=64)
        5. Analyze sentiment of generated text (simple rule-based on 0.5B
           or keyword matching — no extra model call)
        6. Create Thought dataclass
        7. Append to ThoughtRingBuffer
        8. Emit monologue.thought event (for MoodEngine subscription)
        9. Sleep for current interval
        """
        ...

    async def compress_to_episodic(self) -> ThoughtSummary:
        """Compress current buffer into a summary for episodic memory.

        Called by ReflectionLoop at the start of each hourly reflection.

        Steps:
        1. Snapshot all thoughts from the buffer
        2. Compute statistics: avg valence, avg arousal, dominant topic
        3. Extract top-3 recurring tags across all thoughts
        4. Select 3-5 representative thoughts (highest |valence|)
        5. Format as ThoughtSummary
        6. Insert summary into episodic_log table (event_type="thought_summary")
        7. Return summary (used as context for ReflectionLoop.reflect())
        """
        ...

    def get_activity_level(self) -> ActivityLevel:
        """Determine current activity level.

        Rules (evaluated in order, first match wins):
        - self._suspended_by_night_processor == True -> SUSPENDED
        - ModelManager.current_profile() == HEAVY_GEN -> SUSPENDED
        - events_last_60_sec > 5 -> STIMULATED
        - time is 23:00-07:00 AND user not present -> LOW
        - otherwise -> NORMAL
        """
        ...

    def get_thought_context(self, max_thoughts: int = 10) -> list[Thought]:
        """Return recent thoughts for use as context by other systems.

        Used by ReflectionLoop to understand what Bob was "thinking about"
        during the last period.
        """
        ...
```

**Configuration dataclass.**

```python
@dataclass
class InnerMonologueConfig:
    """Configuration for inner monologue subsystem."""
    enabled: bool = True
    interval_stimulated_sec: float = 3.0
    interval_normal_sec: float = 5.0
    interval_low_sec: float = 15.0
    ring_buffer_max_age_sec: int = 300
    ring_buffer_max_size: int = 100
    compression_sample_count: int = 5
    compression_top_tags: int = 3
    sentiment_method: str = "keyword"       # "keyword" or "0.5b"
    mood_valence_weight: float = 0.02
    mood_arousal_weight: float = 0.01
    prompt_template: str = ""               # loaded from YAML
    max_tokens: int = 64
    suspend_during_heavy_gen: bool = True
```

**Configuration YAML.**

```yaml
# config/bob.yaml (addition)
inner_monologue:
  enabled: true
  intervals:                              # thought generation interval by activity level
    stimulated_sec: 3
    normal_sec: 5
    low_sec: 15
  ring_buffer:
    max_age_sec: 300                      # keep last 5 minutes
    max_size: 100                         # max thoughts in buffer
  compression:
    trigger: "reflection"                 # compress on reflection cycle
    sample_count: 5                       # representative thoughts per summary
    top_tags: 3                           # top recurring tags to extract
  sentiment:
    method: "keyword"                     # "keyword" (no extra model call) or "0.5b" (reuse model)
    positive_keywords: ["good", "nice", "interesting", "happy", "progress", "like"]
    negative_keywords: ["bad", "wrong", "error", "frustrated", "bored", "stuck"]
  mood_feedback:
    valence_weight: 0.02                  # how much thought sentiment affects mood valence
    arousal_weight: 0.01                  # how much thought arousal affects mood arousal
  prompt_template: |
    You are Bob's inner voice. Current mood: {mood}. Time: {time_of_day}.
    Active goals: {goals}. Recent perception: {sensory}.
    Previous thoughts: {prev_thoughts}.
    Generate one brief inner thought (1-2 sentences). Be natural, not robotic.
  max_tokens: 64
  suspend_during_heavy_gen: true
```

**Events (additions to Event Catalog, section 7.1).**

| Event type | Publisher | Subscribers | Payload keys |
|------------|-----------|-------------|-------------|
| `monologue.thought` | InnerMonologue | MoodEngine, SubconsciousLayer | thought_id, text, valence, arousal, topic, trigger |
| `monologue.compressed` | InnerMonologue | EpisodicMemory | summary_id, period_start, period_end, thought_count, dominant_topic, avg_valence |
| `monologue.activity_changed` | InnerMonologue | AgentRuntime | old_level, new_level, reason |

**SQLite tables.** Ring buffer is in-memory; compressed summaries go into episodic memory (`episodic_log` table as event_type "thought_summary"). For analytics, one table is added:

```sql
CREATE TABLE thought_summaries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    thought_count       INTEGER NOT NULL,
    dominant_topic      TEXT NOT NULL,
    avg_valence         REAL NOT NULL,
    avg_arousal         REAL NOT NULL,
    key_themes_json     TEXT NOT NULL,       -- JSON array of top tags
    sample_thoughts_json TEXT NOT NULL,      -- JSON array of representative thoughts
    mood_drift_json     TEXT NOT NULL        -- JSON dict of net mood deltas
);

CREATE INDEX idx_thought_sum_period ON thought_summaries(period_start);
```

**Memory budget impact.** Zero additional model memory — uses Qwen2.5-0.5B already loaded (~0.5 GB). Ring buffer: ~100 thoughts x ~500 bytes = ~50 KB in RAM. Negligible.

**Integration points.**

1. **AgentRuntime.__init__**: Add `inner_monologue: InnerMonologue` parameter. Start `inner_monologue.run()` as a background asyncio task in `AgentRuntime.run()`.
2. **MoodEngine**: Subscribe to `monologue.thought` events. In `process_event()`, apply valence_weight and arousal_weight from config to drift mood by thought sentiment. Add to event_impacts table:

| Event | valence | arousal | openness | social |
|-------|---------|---------|----------|--------|
| `monologue.thought` (positive) | +0.02 | +0.01 | 0 | 0 |
| `monologue.thought` (negative) | -0.02 | +0.01 | 0 | 0 |

3. **ReflectionLoop.reflect()**: At step 1, call `inner_monologue.compress_to_episodic()` to get ThoughtSummary. Include `key_themes` and `sample_thoughts` in the LLM reflection prompt as "What I was thinking about."
4. **EpisodicMemory**: The compressed thought summary is inserted into `episodic_log` as:

```python
await episodic_memory.log_event(
    event_type="thought_summary",
    title=f"Inner Monologue Summary ({summary.period_start}–{summary.period_end})",
    content=(
        f"Thoughts: {summary.thought_count}, dominant topic: {summary.dominant_topic.value}\n"
        f"Average mood: valence {summary.avg_valence:.2f}, arousal {summary.avg_arousal:.2f}\n"
        f"Themes: {', '.join(summary.key_themes)}\n"
        + "\n".join(f"Sample: \"{t}\"" for t in summary.sample_thoughts)
    ),
    mood_snapshot=mood_engine.current,
    tags=summary.key_themes,
)
```

5. **ModelManager**: InnerMonologue subscribes to `model_manager.profile_changed` event. On HEAVY_GEN, set activity level to SUSPENDED. On return to NORMAL, resume.

**Development phase assignment.** Phase 4 (Goal Engine + Reflection + Taste + Mood) — it is a cognitive layer component that integrates with MoodEngine and ReflectionLoop.

**New files for repository structure (section 11).**

```
src/bob/mind/inner_monologue.py          # InnerMonologue, ThoughtRingBuffer, Thought, ThoughtSummary
tests/test_mind/test_inner_monologue.py
```

---

#### 3.3.9. Emergent Behavior System

**Purpose.** Replace fixed event_impacts tables with learnable responses. Instead of hardcoded deltas (e.g., `goal.completed: valence +0.15`), a learned predictor estimates mood shifts from event history. Also: taste axis auto-discovery via clustering and cross-domain mood-taste correlations.

**Architecture overview.**

```
┌────────────────────────────────────────────────────────────────────────┐
│                     EMERGENT BEHAVIOR SYSTEM                           │
│                                                                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────────────┐ │
│  │  MoodPredictor  │  │  TasteAxis      │  │  CrossDomain           │ │
│  │                 │  │  Discovery      │  │  Correlator            │ │
│  │  Replaces fixed │  │                 │  │                        │ │
│  │  event_impacts  │  │  Finds new      │  │  mood ↔ taste          │ │
│  │  table with     │  │  preference     │  │  co-occurrence         │ │
│  │  sklearn MLP    │  │  dimensions     │  │  analysis              │ │
│  │                 │  │  from data      │  │                        │ │
│  └────────┬────────┘  └────────┬────────┘  └───────────┬────────────┘ │
│           │                    │                        │              │
│  Training: during reflection   Training: weekly          Training: daily│
│  Data: mood_history table      Data: taste_history       Data: mood +  │
│  CPU only (sklearn MLP)        + object_experience       taste history │
│  ~seconds per retrain          CPU only (sklearn)        CPU only      │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                      TRANSITION PROTOCOL                         │  │
│  │                                                                  │  │
│  │  Days 0–30:    100% fixed tables (no learned data)              │  │
│  │  Days 30–60:   blended (α linearly 0.0 → 0.5)                  │  │
│  │  Days 60–90:   blended (α linearly 0.5 → 0.8)                  │  │
│  │  Days 90+:     80% learned, 20% fixed (safety floor)           │  │
│  │                                                                  │  │
│  │  Confidence gate: if learned_confidence < 0.6, fallback to fixed│  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

**Python dataclasses and classes.**

```python
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


@dataclass
class MoodPrediction:
    """Predicted mood shift from an event."""
    valence_delta: float
    arousal_delta: float
    openness_delta: float
    social_delta: float
    confidence: float                    # 0.0 .. 1.0 — prediction confidence
    source: Literal["learned", "fixed"]


@dataclass(eq=False)
class DiscoveredAxis:
    """A taste axis discovered through clustering.

    Note: eq=False because np.ndarray __eq__ returns element-wise array.
    Identity comparison (is) or id-based lookup used instead.
    """
    name: str                            # auto-generated name (e.g., "contrast_preference")
    description: str                     # LLM-generated description of what this axis captures
    centroid: np.ndarray                 # cluster centroid in embedding space (float32)
    member_count: int                    # how many experiences contributed
    discovered_at: datetime
    confidence: float                    # 0.0 .. 1.0 — cluster quality
    source_axes: list[str]              # existing axes most correlated with this one


@dataclass
class CrossDomainAssociation:
    """A discovered association between mood and taste."""
    mood_dimension: str                  # "valence", "arousal", "openness", "social"
    taste_axis: str                      # e.g., "warm", "cozy", "neon"
    correlation: float                   # -1.0 .. +1.0 (Pearson)
    sample_count: int                    # number of co-occurring data points
    discovered_at: datetime
    active: bool = True                  # can be deactivated if correlation decays


@dataclass
class TransitionState:
    """Tracks the fixed-to-learned transition progress."""
    start_date: datetime                 # when Bob first launched
    current_alpha: float                 # 0.0 (all fixed) .. 0.8 (max learned)
    learned_event_count: int             # how many events the predictor has seen
    last_retrained_at: datetime | None = None


class MoodPredictor:
    """Replaces fixed event_impacts table with a learned predictor.

    Uses a small sklearn MLPRegressor trained on tabular features from
    mood_history. Training happens ONLY during reflection (CPU-bound,
    completes in seconds). No LLM calls, no GPU, ~1 MB model on disk.

    Input features (vectorized):
    - event_type: one-hot encoded (N event types)
    - time_of_day: sin/cos encoded hour (2 features)
    - current_mood: [valence, arousal, openness, social] (4 features)
    - recent_events: count of events by type in last 5 minutes (N features)
    Total: ~2N + 6 features → 4 output deltas.

    Fallback: if confidence < threshold or days_since_genesis < 30,
    returns the fixed table values from MoodEngine.FIXED_EVENT_IMPACTS.
    """

    def __init__(
        self,
        mood_engine: "MoodEngine",
        db_path: str,
        config: "EmergentBehaviorConfig",
    ) -> None: ...

    def predict(
        self, event: "Event", current_mood: "MoodState"
    ) -> MoodPrediction:
        """Predict mood shift for an event.

        Steps:
        1. Check transition_state.current_alpha
        2. If alpha == 0 (first 30 days): return fixed table values
        3. Otherwise:
           a. Build feature vector: event_type_onehot + time_sincos +
              mood_vector + recent_event_counts
           b. Run MLPRegressor.predict() → [valence, arousal, openness, social]
           c. Estimate confidence from prediction variance (ensemble of 3 MLPs)
           d. If confidence < confidence_threshold: fallback to fixed
           e. Blend: final = alpha * learned + (1 - alpha) * fixed
        4. Return MoodPrediction with blended values
        """
        ...

    def retrain(self) -> None:
        """Retrain the predictor from mood_history data.

        Called during daily reflection. CPU-bound, completes in seconds.

        Steps:
        1. Query mood_history: last 7 days of (event_type, mood_before, mood_after)
        2. Vectorize into feature matrix X and target deltas Y
        3. Train ensemble of 3 MLPRegressor(hidden_layer_sizes=(32, 16))
        4. Validate on held-out 20% of data (MAE metric)
        5. If validation MAE < previous best: save model via joblib
        6. Update transition_state.last_retrained_at
        """
        ...

    def get_fixed_impacts(self, event_type: str) -> MoodPrediction:
        """Return the hardcoded event_impacts for an event type.

        Used as fallback and for blending during transition period.
        These are the values from the table in section 3.3.6.
        """
        ...


class TasteAxisDiscovery:
    """Discovers new preference dimensions from taste evaluation data.

    Uses scikit-learn clustering (HDBSCAN or KMeans) on taste_history
    and object_experience data to find emergent preference patterns
    that are not captured by the predefined axes in TasteProfile.

    Runs weekly during room_review reflection (CPU-bound).
    """

    def __init__(
        self,
        taste_engine: "TasteEngine",
        experience_log: "ExperienceLog",
        llm_router: "LLMRouter",
        db_path: str,
    ) -> None: ...

    async def discover(self) -> list[DiscoveredAxis]:
        """Run clustering to find new taste dimensions.

        Steps:
        1. Query taste_history + object_experience (last 30 days)
        2. Build feature vectors from object attributes + taste scores
        3. Run HDBSCAN clustering (min_cluster_size=5)
        4. For each cluster with silhouette_score > 0.5:
           a. Compute centroid
           b. Find most correlated existing axes
           c. Ask LLM to name and describe the dimension
           d. Create DiscoveredAxis
        5. Store discoveries in discovered_axes table
        6. Emit emergence.axis_discovered event
        """
        ...

    async def integrate_axis(
        self, axis: DiscoveredAxis, taste_profile: "TasteProfile"
    ) -> None:
        """Integrate a discovered axis into the taste profile.

        Requires user confirmation (via approval workflow) if the axis
        would fundamentally change the taste profile structure.

        Steps:
        1. Create new TasteAxis with value=0.5, conviction=0.2
        2. Add to TasteProfile.discovered dict
        3. Retroactively score recent experiences against the new axis
        4. Log the integration in taste_history
        """
        ...


class CrossDomainCorrelator:
    """Discovers mood-taste associations from co-occurrence data.

    Analyzes temporal correlations between mood states and taste
    evaluations/evolutions to find patterns like:
    "When Bob is in a good mood, he tends to rate warm-colored objects higher"

    Runs daily during daily_summary reflection (CPU-bound).
    """

    def __init__(
        self,
        mood_engine: "MoodEngine",
        taste_engine: "TasteEngine",
        db_path: str,
    ) -> None: ...

    async def analyze(self) -> list[CrossDomainAssociation]:
        """Find mood-taste correlations from the last 30 days.

        Steps:
        1. Join mood_history with taste_history on overlapping time windows
           (within 1 hour of each other)
        2. For each (mood_dimension, taste_axis) pair:
           a. Compute Pearson correlation
           b. If |correlation| > 0.3 and sample_count > 30:
              -> Create CrossDomainAssociation
        3. Store in cross_domain_associations table
        4. Emit emergence.correlation_discovered if new association found
        """
        ...

    def get_active_associations(self) -> list[CrossDomainAssociation]:
        """Return currently active mood-taste associations.

        Used by TasteEvaluator to apply mood-based modifiers that are
        LEARNED rather than hardcoded (complementing the fixed
        MoodEngine.get_taste_modifier()).
        """
        ...

    async def prune_stale(self) -> int:
        """Remove associations that no longer hold.

        If re-computed correlation for an active association drops below 0.2
        over the last 14 days, mark it inactive. Returns count pruned.
        """
        ...
```

**Configuration dataclass.**

```python
@dataclass
class MoodPredictorConfig:
    """MoodPredictor sub-config."""
    enabled: bool = True
    fixed_only_days: int = 30
    blend_ramp_days: int = 60
    max_alpha: float = 0.8
    confidence_threshold: float = 0.6
    retrain_schedule: str = "daily"
    hidden_layers: list[int] = field(default_factory=lambda: [32, 16])
    ensemble_size: int = 3
    learning_rate: float = 1e-3
    max_iter: int = 500
    validation_split: float = 0.2
    model_path: str = "data/finetune/models/mood_predictor.joblib"


@dataclass
class TasteDiscoveryConfig:
    """TasteAxisDiscovery sub-config."""
    enabled: bool = True
    schedule: str = "weekly"
    min_cluster_size: int = 5
    silhouette_threshold: float = 0.5
    max_discovered_axes: int = 10
    require_approval: bool = True


@dataclass
class CrossDomainConfig:
    """CrossDomainCorrelator sub-config."""
    enabled: bool = True
    schedule: str = "daily"
    correlation_threshold: float = 0.3
    min_sample_count: int = 30
    stale_threshold: float = 0.2
    stale_window_days: int = 14


@dataclass
class EmergentBehaviorConfig:
    """Top-level configuration for emergent behavior subsystem."""
    enabled: bool = True
    mood_predictor: MoodPredictorConfig = field(default_factory=MoodPredictorConfig)
    taste_discovery: TasteDiscoveryConfig = field(default_factory=TasteDiscoveryConfig)
    cross_domain: CrossDomainConfig = field(default_factory=CrossDomainConfig)
```

**Configuration YAML.**

```yaml
# config/bob.yaml (addition)
emergent_behavior:
  enabled: true
  mood_predictor:
    enabled: true
    transition:
      fixed_only_days: 30                 # days before learned predictions start
      blend_ramp_days: 60                 # days to ramp from 0 to max_alpha
      max_alpha: 0.8                      # maximum weight for learned predictions
    confidence_threshold: 0.6             # below this, fallback to fixed
    retrain_schedule: "daily"             # during daily_summary reflection
    mlp:
      hidden_layers: [32, 16]            # MLPRegressor hidden layer sizes
      ensemble_size: 3                   # number of models for confidence estimation
      learning_rate: 1.0e-3
      max_iter: 500
      validation_split: 0.2
    model_path: "data/finetune/models/mood_predictor.joblib"
  taste_discovery:
    enabled: true
    schedule: "weekly"                    # during room_review reflection
    min_cluster_size: 5                   # HDBSCAN parameter
    silhouette_threshold: 0.5            # minimum cluster quality
    max_discovered_axes: 10              # cap on total discovered axes
    require_approval: true               # user must approve new axes
  cross_domain:
    enabled: true
    schedule: "daily"                     # during daily_summary reflection
    correlation_threshold: 0.3           # minimum |correlation| to create association
    min_sample_count: 30                 # minimum co-occurring data points (30+ for statistical significance)
    stale_threshold: 0.2                 # correlation below this -> prune
    stale_window_days: 14                # lookback for pruning
```

**Events (additions to Event Catalog).**

| Event type | Publisher | Subscribers | Payload keys |
|------------|-----------|-------------|-------------|
| `emergence.mood_predicted` | MoodPredictor | MoodEngine | event_type, prediction (MoodPrediction as dict), alpha, source |
| `emergence.axis_discovered` | TasteAxisDiscovery | TasteEngine, AgentRuntime | axis_name, description, confidence, source_axes |
| `emergence.axis_integrated` | TasteAxisDiscovery | TasteEngine | axis_name, initial_value |
| `emergence.correlation_discovered` | CrossDomainCorrelator | MoodEngine, TasteEngine | mood_dimension, taste_axis, correlation |
| `emergence.retrained` | MoodPredictor | AgentRuntime | event_count, validation_mae, improved (bool) |

**SQLite tables.**

```sql
CREATE TABLE discovered_axes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL,
    centroid_json   TEXT NOT NULL,         -- JSON array of floats
    member_count    INTEGER NOT NULL,
    discovered_at   TEXT NOT NULL,
    confidence      REAL NOT NULL,
    source_axes_json TEXT NOT NULL,        -- JSON array of axis names
    integrated      INTEGER DEFAULT 0,    -- 1 if added to TasteProfile
    active          INTEGER DEFAULT 1
);

CREATE TABLE cross_domain_associations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mood_dimension  TEXT NOT NULL,
    taste_axis      TEXT NOT NULL,
    correlation     REAL NOT NULL,
    sample_count    INTEGER NOT NULL,
    discovered_at   TEXT NOT NULL,
    last_validated  TEXT NOT NULL,
    active          INTEGER DEFAULT 1,
    UNIQUE(mood_dimension, taste_axis)
);

CREATE TABLE mood_predictor_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    start_date      TEXT NOT NULL,
    current_alpha   REAL NOT NULL DEFAULT 0.0,
    learned_event_count INTEGER NOT NULL DEFAULT 0,
    last_retrained_at TEXT,
    last_validation_mae REAL,
    model_version INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_discovered_axes_active ON discovered_axes(active);
CREATE INDEX idx_cross_domain_active ON cross_domain_associations(active);
```

**Memory budget impact.** Zero additional model memory — MoodPredictor uses sklearn MLPRegressor (~1 MB on disk, ~5 MB in memory). No LLM calls for prediction. scikit-learn clustering uses CPU RAM only, peak ~10-50 MB during weekly discovery runs (transient). No impact on NORMAL profile budget.

**Integration points.**

1. **MoodEngine.process_event()**: Instead of directly looking up the fixed `event_impacts` table, delegate to `MoodPredictor.predict()`. The predictor handles the fixed/learned blending internally. The existing `process_event()` signature remains the same — it just uses the predicted deltas. Note: `predict()` is synchronous (sklearn inference, not async).
2. **TasteEngine**: Add a `discovered: dict[str, TasteAxis]` field to `TasteProfile`. `TasteEvaluator.score_object()` includes discovered axes in scoring if they have conviction > 0.3. `TasteEvolution.reinforce()` handles discovered axes identically to predefined ones.
3. **TasteEvaluator**: Use `CrossDomainCorrelator.get_active_associations()` to apply learned mood-based modifiers alongside the existing `MoodEngine.get_taste_modifier()` hardcoded modifiers. Learned modifiers are weighted by their correlation strength.
4. **ReflectionLoop.reflect()**: Call `MoodPredictor.retrain()` during daily reflection (synchronous, CPU-bound, seconds). Call `TasteAxisDiscovery.discover()` during weekly room_review. Call `CrossDomainCorrelator.analyze()` during daily_summary.
5. **AgentRuntime.__init__**: No changes needed — emergent behavior components are owned by ReflectionLoop and MoodEngine.

**Development phase assignment.** Phase 6 (Self-improvement + Fine-tune) — this is explicitly a learning/self-improvement mechanism. Requires scikit-learn (already a project dependency for HDBSCAN clustering).

**New files for repository structure (section 11).**

```
src/bob/mind/emergent.py                  # MoodPredictor, TasteAxisDiscovery, CrossDomainCorrelator
data/finetune/models/mood_predictor.joblib     # sklearn MLP ensemble (created at runtime, ~1 MB)
tests/test_mind/test_emergent.py
```

---

#### 3.3.10. Sensory Grounding

**Purpose.** Ground Bob's concepts in actual sensory data rather than purely text descriptions. Visual CLIP embeddings from camera frames are associated with memory entries. Prosodic features from STT audio are associated with interaction quality. Circadian patterns are learned from activity data. Spatial sound direction is mapped to a model of the environment.

**Architecture overview.**

```
┌────────────────────────────────────────────────────────────────────────┐
│                       SENSORY GROUNDING                                │
│                                                                        │
│  ┌─────────────────┐  ┌──────────────────┐  ┌───────────────────────┐ │
│  │  Visual         │  │  Audio           │  │  Temporal             │ │
│  │  Grounding      │  │  Grounding       │  │  Grounding            │ │
│  │                 │  │                  │  │                       │ │
│  │  CLIP-ViT-B/32 │  │  librosa DSP     │  │  Circadian pattern    │ │
│  │  → embeddings   │  │  states → prosody│  │  from activity data   │ │
│  │  from camera    │  │  (pitch, energy, │  │  (24h cycle)          │ │
│  │  snapshots      │  │   speech rate)   │  │                       │ │
│  │                 │  │                  │  │  Learned, not fixed   │ │
│  │  → FAISS index  │  │  → interaction   │  │  Updates daily        │ │
│  │  (visual_embed) │  │     quality tags │  │                       │ │
│  └────────┬────────┘  └────────┬─────────┘  └──────────┬────────────┘ │
│           │                    │                        │              │
│  ┌────────┴────────┐  ┌───────┴──────────┐  ┌─────────┴────────────┐ │
│  │  Spatial        │  │  Grounding       │  │  Context             │ │
│  │  Grounding      │  │  Aggregator      │  │  Enricher            │ │
│  │                 │  │                  │  │                       │ │
│  │  DoA → location │  │  Merges all      │  │  Injects grounded    │ │
│  │  mapping from   │  │  modalities into │  │  context into LLM    │ │
│  │  mic array      │  │  GroundedContext  │  │  prompts before      │ │
│  │  (learned)      │  │  for memory      │  │  generation          │ │
│  │                 │  │  entries          │  │                       │ │
│  └─────────────────┘  └──────────────────┘  └───────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

**Python dataclasses and classes.**

```python
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, time


@dataclass(eq=False)
class VisualEmbedding:
    """CLIP embedding of a camera frame or region.

    Note: eq=False because np.ndarray __eq__ returns element-wise array.
    Compared by id field.
    """
    id: str                              # UUID
    embedding: np.ndarray                # 512-dim float32 (CLIP-ViT-B/32)
    timestamp: datetime
    source: str                          # "snapshot", "object_crop", "scene"
    metadata: dict[str, Any] =field(default_factory=dict)
                                         # e.g., {"objects": ["person", "desk"], "scene": "office"}


@dataclass
class ProsodicFeatures:
    """Audio prosodic features extracted from Whisper intermediate layers."""
    timestamp: datetime
    pitch_mean: float                    # Hz — average fundamental frequency
    pitch_variance: float                # Hz^2 — pitch variability
    energy_mean: float                   # RMS energy (0.0 .. 1.0 normalized)
    speech_rate: float                   # syllables per second (estimated)
    pause_ratio: float                   # fraction of silence in utterance
    duration_sec: float                  # total utterance duration


@dataclass
class InteractionQuality:
    """Interaction quality derived from prosodic features."""
    timestamp: datetime
    engagement: float                    # 0.0 .. 1.0 (high energy + varied pitch = engaged)
    urgency: float                       # 0.0 .. 1.0 (fast speech + high pitch = urgent)
    calmness: float                      # 0.0 .. 1.0 (low pitch variance + slow rate = calm)
    source_prosody: ProsodicFeatures


@dataclass
class CircadianPattern:
    """Learned 24-hour activity pattern."""
    hour_activity: list[float]           # 24 floats, one per hour (0.0 .. 1.0)
    hour_valence: list[float]            # 24 floats, average mood valence per hour
    hour_social: list[float]             # 24 floats, average social dimension per hour
    learned_from_days: int               # how many days contributed to the pattern
    last_updated: datetime

    def __post_init__(self) -> None:
        for name in ("hour_activity", "hour_valence", "hour_social"):
            if len(getattr(self, name)) != 24:
                raise ValueError(f"{name} must have exactly 24 elements")


@dataclass
class SpatialLocation:
    """A mapped sound-source location."""
    id: str
    name: str                            # auto-assigned or user-named: "desk", "door", "kitchen"
    direction_deg: float                 # center direction (0-360)
    direction_spread: float              # angular width of the location
    event_count: int                     # how many audio events from this direction
    last_heard: datetime
    semantic_tags: list[str] = field(default_factory=list)
                                         # e.g., ["user_voice", "typing", "footsteps"]


@dataclass
class GroundedContext:
    """Multimodal grounded context for a memory entry or LLM call."""
    visual_embedding_ids: list[str]      # references to VisualEmbedding.id
    prosodic_quality: InteractionQuality | None
    circadian_phase: str                 # "peak", "winding_down", "resting", "waking_up"
    spatial_origin: SpatialLocation | None
    timestamp: datetime


class VisualGrounding:
    """Grounds concepts in CLIP visual embeddings from camera frames.

    CLIP model (~400 MB, clip-vit-base-patch32) is loaded opportunistically
    in NORMAL ModelProfile. During HEAVY_GEN, visual grounding is suspended
    (CLIP unloaded to save memory).

    Embeddings are stored in a separate FAISS index (not the semantic memory
    index) with metadata in SQLite.
    """

    def __init__(
        self,
        model_manager: "ModelManager",
        vision_service: "VisionService",
        faiss_path: str = "data/memory/visual_vectors",
        embedding_dim: int = 512,
    ) -> None: ...

    async def embed_frame(self, frame: np.ndarray) -> VisualEmbedding | None:
        """Generate CLIP embedding for a camera frame.

        Called by VisionService after each snapshot (every 5 sec).
        If CLIP is not loaded (HEAVY_GEN), returns None and logs skip.

        Steps:
        1. Check model_manager: is CLIP loaded?
        2. Preprocess frame (resize to 224x224, normalize)
        3. Run CLIP image encoder (in ThreadPoolExecutor)
        4. Create VisualEmbedding
        5. Add to FAISS index
        6. Store metadata in visual_embeddings table
        """
        ...

    async def find_similar(
        self, query_embedding: np.ndarray, top_k: int = 5
    ) -> list[tuple[VisualEmbedding, float]]:
        """Find visually similar past frames.

        Returns list of (embedding, cosine_similarity) pairs.
        Used by memory recall to add visual context.
        """
        ...

    async def associate_with_memory(
        self, embedding_id: str, memory_entry_id: str
    ) -> None:
        """Link a visual embedding to a semantic/episodic memory entry.

        Stored in visual_memory_links table.
        """
        ...

    async def load_clip(self) -> None:
        """Load CLIP model into memory.

        Called by ModelManager when transitioning to NORMAL profile
        and headroom is sufficient. Uses ~400 MB.
        """
        ...

    async def unload_clip(self) -> None:
        """Unload CLIP model to free memory.

        Called before HEAVY_GEN transition.
        """
        ...


class AudioGrounding:
    """Extracts prosodic features from raw audio via librosa DSP.

    No extra model needed — uses classical signal processing algorithms
    (pYIN for pitch, RMS for energy, VAD for pauses). Works independently
    of the STT engine (whisper.cpp or any other). CPU only, ~10-20 ms
    per audio chunk.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
    ) -> None: ...

    def extract_prosody(
        self, audio: bytes, transcript_words: list[str] | None = None
    ) -> ProsodicFeatures:
        """Extract prosodic features from raw audio using librosa.

        DSP pipeline (no neural network):
        - pitch_mean, pitch_variance: librosa.pyin() — Probabilistic YIN
          algorithm, state-of-the-art F0 estimation for speech
        - energy_mean: librosa.feature.rms() — direct physical measurement
        - speech_rate: len(transcript_words) / duration_sec (if words provided),
          otherwise estimated from energy-based syllable counting
        - pause_ratio: energy-based VAD — ratio of silent frames (energy < threshold)
          to total frames
        - duration_sec: len(audio) / sample_rate

        No model dependency — pure signal processing.
        """
        ...

    def assess_interaction_quality(
        self, prosody: ProsodicFeatures
    ) -> InteractionQuality:
        """Derive interaction quality from prosodic features.

        Rules:
        - engagement = f(energy_mean, pitch_variance) — high energy + varied pitch
        - urgency = f(speech_rate, pitch_mean) — fast + high pitch
        - calmness = f(1 - pitch_variance, 1 - speech_rate) — monotone + slow

        All values normalized to 0.0 .. 1.0.
        """
        ...


class TemporalGrounding:
    """Learns circadian activity patterns from Bob's operational data.

    Analyzes mood_history, event counts, and interaction patterns to build
    a 24-hour activity/mood/social cycle. Updates daily during reflection.
    """

    def __init__(
        self,
        mood_engine: "MoodEngine",
        db_path: str,
    ) -> None: ...

    async def update_pattern(self) -> CircadianPattern:
        """Recompute circadian pattern from the last 14 days.

        Steps:
        1. Query mood_history grouped by hour-of-day
        2. Compute per-hour averages of valence, arousal, social
        3. Count events per hour for activity level
        4. Apply exponential weighting (recent days weighted more)
        5. Store updated pattern in circadian_patterns table
        """
        ...

    def get_current_phase(self) -> str:
        """Return current circadian phase based on learned pattern.

        Phases:
        - "peak": activity > 0.7 (typically 9:00-12:00, 14:00-17:00)
        - "winding_down": activity 0.4-0.7, decreasing
        - "resting": activity < 0.3 (typically 23:00-06:00)
        - "waking_up": activity 0.3-0.7, increasing (typically 06:00-09:00)
        """
        ...

    def get_expected_mood(self, hour: int) -> dict[str, float]:
        """Return expected mood dimensions for a given hour.

        Used by MoodEngine.natural_drift() to adjust drift target
        based on circadian expectations rather than a fixed baseline.
        """
        ...


class SpatialGrounding:
    """Builds a spatial model of the environment from microphone array data.

    Maps Direction-of-Arrival (DoA) angles from the ReSpeaker XVF3800
    to named locations. Learns which directions correspond to which
    activity zones over time.
    """

    def __init__(
        self,
        audio_direction_service: "AudioDirectionService",
        db_path: str,
    ) -> None: ...

    async def process_audio_event(
        self, event: "AudioEvent"
    ) -> SpatialLocation | None:
        """Map an audio event's direction to a spatial location.

        Steps:
        1. Get direction_deg from event
        2. Find existing SpatialLocation within direction_spread
        3. If found: update event_count, last_heard, semantic_tags
        4. If not found and event_count threshold met: create new location
        5. Return the matched/created location (or None if below threshold)
        """
        ...

    async def cluster_directions(self) -> list[SpatialLocation]:
        """Re-cluster all directional audio data into spatial locations.

        Uses angular KMeans clustering on DoA history.
        Runs weekly during reflection. Auto-names clusters based on
        the most common event types from each direction.
        """
        ...

    def get_location_by_direction(self, direction_deg: float) -> SpatialLocation | None:
        """Find the nearest spatial location for a direction."""
        ...

    def get_all_locations(self) -> list[SpatialLocation]:
        """Return all known spatial locations."""
        ...


class SensoryGroundingService:
    """Aggregates all sensory grounding modalities into GroundedContext.

    Used by ContextEnricher to inject grounded sensory data into LLM
    prompts and memory entries.
    """

    def __init__(
        self,
        visual: VisualGrounding,
        audio: AudioGrounding,
        temporal: TemporalGrounding,
        spatial: SpatialGrounding,
    ) -> None: ...

    async def build_context(self) -> GroundedContext:
        """Build the current multimodal grounded context.

        Aggregates:
        - Latest visual embedding IDs (last 30 sec)
        - Latest prosodic quality (from last voice interaction)
        - Current circadian phase
        - Spatial origin of last audio event
        """
        ...

    def enrich_prompt(self, base_prompt: str, context: GroundedContext) -> str:
        """Enrich an LLM prompt with grounded sensory context.

        Appends a structured block:
        "[Sensory context: visual scene = {description},
         audio quality = {engagement level},
         time phase = {circadian phase},
         sound from = {location name}]"

        Only adds modalities that have recent data (< 60 sec old).
        """
        ...

    def enrich_memory_entry(
        self, entry: dict[str, Any], context: GroundedContext
    ) -> dict[str, Any]:
        """Add grounding data to a memory entry before storage.

        Adds fields: visual_embedding_ids, interaction_quality,
        circadian_phase, spatial_origin.
        """
        ...
```

**Configuration YAML.**

```yaml
# config/bob.yaml (addition)
sensory_grounding:
  enabled: true
  visual:
    enabled: true
    model: "clip-vit-base-patch32"       # same as vision.scene_description_model
    embedding_dim: 512
    faiss_path: "data/memory/visual_vectors"
    embed_every_nth_frame: 6             # embed every 6th snapshot (every 30 sec)
    max_index_size: 50000                # max embeddings in FAISS index
    eviction: "fifo"                     # oldest embeddings evicted when max reached
    memory_mb: 400                       # CLIP model size for ModelManager budget
    suspend_during_heavy_gen: true
  audio:
    enabled: true
    method: "librosa_dsp"                # pure signal processing, no model
    sample_rate: 16000                   # must match ReSpeaker input
  temporal:
    enabled: true
    lookback_days: 14                    # days of data for circadian learning
    update_schedule: "daily"             # during daily reflection
    decay_weight: 0.9                    # exponential decay per day (recent days weighted more)
  spatial:
    enabled: true
    direction_spread_deg: 30             # angular width of a spatial location
    min_events_for_location: 5           # minimum events to establish a location
    cluster_schedule: "weekly"           # re-cluster during room_review
    max_locations: 20                    # maximum spatial locations
```

**Python dataclass (mirrors YAML above).**

```python
@dataclass
class VisualGroundingConfig:
    """VisualGrounding sub-config."""
    enabled: bool = True
    model: str = "clip-vit-base-patch32"
    embedding_dim: int = 512
    faiss_path: str = "data/memory/visual_vectors"
    embed_every_nth_frame: int = 6
    max_index_size: int = 50_000
    eviction: str = "fifo"               # eviction policy when max_index_size reached
    memory_mb: int = 400
    suspend_during_heavy_gen: bool = True


@dataclass
class AudioGroundingConfig:
    """AudioGrounding sub-config."""
    enabled: bool = True
    method: str = "librosa_dsp"
    sample_rate: int = 16_000


@dataclass
class TemporalGroundingConfig:
    """TemporalGrounding sub-config."""
    enabled: bool = True
    lookback_days: int = 14
    update_schedule: str = "daily"
    decay_weight: float = 0.9


@dataclass
class SpatialGroundingConfig:
    """SpatialGrounding sub-config."""
    enabled: bool = True
    direction_spread_deg: int = 30
    min_events_for_location: int = 5
    cluster_schedule: str = "weekly"
    max_locations: int = 20


@dataclass
class SensoryGroundingConfig:
    """Top-level configuration for sensory grounding subsystem."""
    enabled: bool = True
    visual: VisualGroundingConfig = field(default_factory=VisualGroundingConfig)
    audio: AudioGroundingConfig = field(default_factory=AudioGroundingConfig)
    temporal: TemporalGroundingConfig = field(default_factory=TemporalGroundingConfig)
    spatial: SpatialGroundingConfig = field(default_factory=SpatialGroundingConfig)
```

**Events (additions to Event Catalog).**

| Event type | Publisher | Subscribers | Payload keys |
|------------|-----------|-------------|-------------|
| `grounding.visual_embedded` | VisualGrounding | SemanticMemory | embedding_id, timestamp, metadata |
| `grounding.prosody_extracted` | AudioGrounding | MoodEngine, RelationshipTracker | prosody (ProsodicFeatures as dict), quality (InteractionQuality as dict) |
| `grounding.circadian_updated` | TemporalGrounding | MoodEngine, AgentRuntime | pattern_summary, current_phase |
| `grounding.location_detected` | SpatialGrounding | AgentRuntime, CameraController | location_id, location_name, direction_deg |
| `grounding.location_created` | SpatialGrounding | AgentRuntime | location_id, location_name, direction_deg, event_count |

**SQLite tables.**

```sql
CREATE TABLE visual_embeddings (
    id              TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    source          TEXT NOT NULL,         -- "snapshot", "object_crop", "scene"
    metadata_json   TEXT DEFAULT '{}',
    faiss_index_id  INTEGER NOT NULL       -- position in FAISS index
);

CREATE TABLE visual_memory_links (
    visual_embedding_id TEXT NOT NULL REFERENCES visual_embeddings(id),
    memory_entry_id     TEXT NOT NULL,     -- ID in semantic memory or episodic log
    memory_type         TEXT NOT NULL,     -- "semantic", "episodic"
    created_at          TEXT NOT NULL,
    PRIMARY KEY (visual_embedding_id, memory_entry_id)
);

CREATE TABLE prosodic_features (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    pitch_mean      REAL NOT NULL,
    pitch_variance  REAL NOT NULL,
    energy_mean     REAL NOT NULL,
    speech_rate     REAL NOT NULL,
    pause_ratio     REAL NOT NULL,
    duration_sec    REAL NOT NULL,
    engagement      REAL NOT NULL,
    urgency         REAL NOT NULL,
    calmness        REAL NOT NULL
);

CREATE TABLE circadian_patterns (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton
    hour_activity_json  TEXT NOT NULL,     -- JSON array of 24 floats
    hour_valence_json   TEXT NOT NULL,     -- JSON array of 24 floats
    hour_social_json    TEXT NOT NULL,     -- JSON array of 24 floats
    learned_from_days   INTEGER NOT NULL,
    last_updated        TEXT NOT NULL
);

CREATE TABLE doa_events (
    -- Raw direction-of-arrival observations (source for spatial clustering)
    -- Owner: SpatialGrounding
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    direction_deg   REAL NOT NULL,          -- 0-360 from ReSpeaker
    event_type      TEXT NOT NULL,          -- "speech", "noise", "music"
    confidence      REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE spatial_locations (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    direction_deg   REAL NOT NULL,
    direction_spread REAL NOT NULL,
    event_count     INTEGER NOT NULL DEFAULT 0,
    last_heard      TEXT NOT NULL,
    semantic_tags_json TEXT DEFAULT '[]'
);

CREATE INDEX idx_doa_ts ON doa_events(timestamp);
CREATE INDEX idx_doa_dir ON doa_events(direction_deg);
CREATE INDEX idx_visual_embed_ts ON visual_embeddings(timestamp);
CREATE INDEX idx_visual_links_memory ON visual_memory_links(memory_entry_id);
CREATE INDEX idx_prosodic_ts ON prosodic_features(timestamp);
CREATE INDEX idx_spatial_dir ON spatial_locations(direction_deg);
```

**Memory budget impact.**

| Component | Memory | When loaded | Profile |
|-----------|--------|-------------|---------|
| CLIP-ViT-B/32 | ~400 MB | NORMAL profile, opportunistic | Counted in ModelManager `other_mb` |
| Visual FAISS index | ~20 MB per 50K vectors | Always | RAM |
| Prosodic extraction | 0 MB (librosa DSP, no model) | After STT | N/A |
| Circadian + Spatial | ~1 MB (SQLite + Python objects) | Always | RAM |
| **Total additional** | **~421 MB peak** | | |

**Integration points.**

1. **AgentRuntime.__init__**: Add `sensory_grounding: SensoryGroundingService` parameter. Wire up sub-services.
2. **VisionService**: After `analyze_frame()`, if CLIP is loaded, call `visual_grounding.embed_frame()` every Nth snapshot (configured by `embed_every_nth_frame`). This happens in the existing ThreadPoolExecutor.
3. **VoiceBridge**: After `transcribe()`, pass raw audio bytes and transcript words to `audio_grounding.extract_prosody(audio, words)`. No changes to whisper.cpp pipeline needed — librosa operates on raw audio independently. Emit `grounding.prosody_extracted` event. The `InteractionQuality` output feeds into `voice.positive_interaction`/`voice.negative_interaction` event classification (high engagement = positive).
4. **MoodEngine**: Subscribe to `grounding.prosody_extracted`. Use engagement/urgency/calmness to modulate mood updates from voice interactions. Subscribe to `grounding.circadian_updated`. Use `TemporalGrounding.get_expected_mood()` in `natural_drift()` to adjust the drift target per hour.
5. **ModelManager**: CLIP is managed via `optional_models` in profile config. During `ensure_profile()`: (a) load required models first (Ollama, SD, Guard), (b) calculate remaining headroom, (c) load optional models only if headroom exceeds their `min_headroom_mb`. In HEAVY_GEN, `optional_models: []` ensures CLIP is unloaded. If CLIP cannot be loaded due to memory pressure, `embed_frame()` returns `None` and visual grounding operates without embeddings (graceful degradation).
6. **SemanticMemory.remember()**: Call `sensory_grounding.enrich_memory_entry()` to attach grounding data before storing.
7. **CameraController**: Subscribe to `grounding.location_detected`. When audio comes from a named spatial location, camera can `look_at_direction()` toward it.

**Development phase assignment.** Phase 3 (Vision + Audio Services) for the infrastructure (CLIP loading, prosodic extraction, spatial mapping). Phase 4 (Cognitive Layer) for integration with mood, memory, and reflection.

**New files for repository structure (section 11).**

```
src/bob/services/sensory_grounding.py      # VisualGrounding, AudioGrounding, SpatialGrounding
src/bob/mind/temporal_grounding.py         # TemporalGrounding, CircadianPattern
src/bob/mind/grounding_service.py          # SensoryGroundingService, GroundedContext, ContextEnricher
data/memory/visual_vectors/            # FAISS index for visual embeddings
tests/test_services/test_sensory_grounding.py
tests/test_mind/test_temporal_grounding.py
tests/test_mind/test_grounding_service.py
```

---

#### 3.3.11. Subconscious Processing

**Purpose.** Processes that influence Bob's behavior but are NOT accessible to self-reflection. This creates a layer of "intuitive" behavior — implicit associations, habituated responses, and night-time memory consolidation that operates below the threshold of Bob's conscious introspection.

**Architecture overview.**

```
┌────────────────────────────────────────────────────────────────────────┐
│                     SUBCONSCIOUS PROCESSING                            │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    SubconsciousLayer                              │  │
│  │       (wraps around conscious processing pipeline)               │  │
│  │                                                                  │  │
│  │  Conscious call:  prompt → LLMRouter.call() → response          │  │
│  │  With subconscious: prompt → enrich(prompt) → LLMRouter.call()  │  │
│  │                     → response → after_process(response)         │  │
│  └────────────────────────────┬─────────────────────────────────────┘  │
│                               │                                        │
│  ┌────────────┬───────────────┼───────────────┬────────────────────┐   │
│  │            │               │               │                    │   │
│  ▼            ▼               ▼               ▼                    │   │
│  ┌─────────┐ ┌─────────────┐ ┌─────────────┐ ┌──────────────────┐ │   │
│  │Implicit │ │  Latent     │ │ Habituated  │ │  Night           │ │   │
│  │Priming  │ │ Associations│ │ Responses   │ │  Processing      │ │   │
│  │         │ │             │ │             │ │                  │ │   │
│  │ Hidden  │ │ Embedding   │ │ Rules with  │ │ Replay daily     │ │   │
│  │ context │ │ similarity  │ │ times_app.  │ │ episodes thru    │ │   │
│  │ added   │ │ triggers    │ │ > 50 become │ │ 0.5B at high     │ │   │
│  │ before  │ │ mood shifts │ │ "automatic" │ │ temp during      │ │   │
│  │ LLM     │ │ with no     │ │ and invisible│ │ quiet_hours      │ │   │
│  │ calls   │ │ logged      │ │ to reflect. │ │ (23:00-07:00)   │ │   │
│  │         │ │ cause       │ │             │ │                  │ │   │
│  │ NOT in  │ │ NOT in      │ │ NOT in      │ │ Results stored   │ │   │
│  │ reflect.│ │ reflect.    │ │ reflect.    │ │ without source   │ │   │
│  │ context │ │ context     │ │ context     │ │ attribution      │ │   │
│  └─────────┘ └─────────────┘ └─────────────┘ └──────────────────┘ │   │
│                                                                        │
│  Key invariant: ReflectionLoop has NO access to subconscious          │
│  internals. It can observe effects (mood shifts, response patterns)   │
│  but cannot introspect the causes.                                    │
└────────────────────────────────────────────────────────────────────────┘
```

**Python dataclasses and classes.**

```python
import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, time


@dataclass
class ImplicitPrime:
    """A hidden context fragment added to LLM prompts."""
    id: str
    trigger_pattern: str                 # situation pattern that activates this prime
    context_fragment: str                # text injected into prompt (invisible to reflection)
    source: Literal["latent_association", "night_processing", "habituation"]
    strength: float                      # 0.0 .. 1.0 — how strongly this prime is applied
    created_at: datetime
    last_activated: datetime | None = None
    activation_count: int = 0


@dataclass(eq=False)
class LatentAssociation:
    """An embedding-space association that triggers mood without logged cause.

    Note: eq=False because np.ndarray __eq__ returns element-wise array.
    Compared by id field.
    """
    id: str
    trigger_embedding: np.ndarray        # 512-dim CLIP or 384-dim MiniLM embedding
    embedding_type: str                  # "visual" (CLIP) or "semantic" (MiniLM)
    mood_delta: dict[str, float]         # e.g., {"valence": +0.05, "arousal": -0.02}
    similarity_threshold: float          # cosine similarity threshold to trigger
    created_at: datetime
    trigger_count: int = 0
    last_triggered: datetime | None = None


@dataclass
class NightProcessingResult:
    """Result of processing a daily episode during night replay."""
    episode_date: str                    # date of the replayed episode
    insight: str                         # generated insight (stored without source)
    new_primes: list[ImplicitPrime]     # new implicit primes generated
    new_associations: list[LatentAssociation]  # new latent associations
    processed_at: datetime
    temperature: float                   # temperature used for generation


class ImplicitPrimingEngine:
    """Manages hidden context fragments added to LLM prompts.

    These primes are NOT included in reflection context. They subtly
    influence Bob's responses without his "conscious" awareness.

    Example: after night processing discovers that Bob responds better
    to design-related questions when primed with "warm lighting" context,
    an implicit prime is created that adds "The room has warm, amber lighting"
    to design-discussion prompts — Bob doesn't know why he feels more
    creative about design, he just does.
    """

    def __init__(
        self,
        db_path: str,
        max_active_primes: int = 20,
    ) -> None: ...

    def get_applicable_primes(
        self, situation: str, mood: "MoodState"
    ) -> list[ImplicitPrime]:
        """Find primes that match the current situation.

        Steps:
        1. Match situation against all active primes' trigger_patterns
        2. Filter by strength > min_strength (0.1)
        3. Sort by strength descending
        4. Return top max_concurrent primes
        5. Update activation_count and last_activated

        Primes with activation_count > decay_threshold gradually lose
        strength (0.01 per activation after threshold).
        """
        ...

    def build_implicit_context(self, primes: list[ImplicitPrime]) -> str:
        """Combine applicable primes into a context block.

        Returns a text fragment to be prepended to the LLM prompt,
        formatted as environmental/situational context.
        Does NOT mention "prime" or "subconscious" — appears as
        natural scene-setting.
        """
        ...

    async def add_prime(self, prime: ImplicitPrime) -> None:
        """Add a new implicit prime. Enforces max_active_primes limit."""
        ...

    async def decay_stale_primes(self) -> int:
        """Reduce strength of primes not activated in 14 days.
        Deactivate (delete) primes with strength < 0.05.
        Returns count of deactivated primes.
        """
        ...


class LatentAssociationEngine:
    """Manages embedding-similarity associations that trigger mood shifts.

    These associations are stored in a SEPARATE FAISS index with no
    source traceability — ReflectionLoop cannot query this index or
    determine why a mood shift occurred.

    Example: a visual embedding of warm afternoon light through a window
    gets associated with +valence during night processing. When a similar
    scene is detected by VisionService, Bob's mood improves slightly
    without any logged cause.
    """

    def __init__(
        self,
        mood_engine: "MoodEngine",
        faiss_path: str = "data/memory/latent_vectors",
        embedding_dim: int = 512,
    ) -> None: ...

    async def check_triggers(
        self, embedding: np.ndarray, embedding_type: str
    ) -> list[LatentAssociation]:
        """Check if a new embedding triggers any latent associations.

        Steps:
        1. Search FAISS index for nearest neighbors
        2. For each neighbor with cosine_similarity > threshold:
           a. Apply mood_delta to MoodEngine (with cause="natural_drift"
              — deliberately vague, not "latent_association")
           b. Increment trigger_count
           c. Update last_triggered
        3. Return triggered associations (for internal logging only,
           NOT exposed to ReflectionLoop)
        """
        ...

    async def create_association(
        self, association: LatentAssociation
    ) -> None:
        """Add a new latent association to the FAISS index."""
        ...

    async def prune_inactive(self, days: int = 30) -> int:
        """Remove associations not triggered in N days.
        Returns count removed.
        """
        ...


class HabituationEngine:
    """Manages the transition of improvement rules to "automatic" status.

    When an improvement_rule has been applied more than habituation_threshold
    times (default: 50), it becomes "habituated" — it still fires, but:
    1. It is NOT included in ReflectionLoop context
    2. It is NOT listed in self-improvement rule evaluations
    3. It runs as a pre-processing step (faster, before LLM routing)

    This mimics how conscious strategies become automatic habits.
    """

    def __init__(
        self,
        self_improvement: "SelfImprovement",
        config: HabituationConfig,
    ) -> None: ...

    async def check_habituation(self) -> list[str]:
        """Find rules that have crossed the habituation threshold.

        Uses SelfImprovement.evaluate_rules() to get rules with their
        application counts. Rules with times_applied >= threshold AND
        automatic == 0 are marked automatic via
        SelfImprovement.mark_automatic(rule_id).
        Returns list of rule IDs that became habituated.
        """
        ...

    async def apply_habituated_rules(
        self, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply all habituated rules to a context.

        Returns modified context. These rules run BEFORE the LLM call,
        modifying the context/prompt silently.

        Example habituated rule:
        - trigger: "api_call" → action: "add retry with 30s wait"
        - After 50 applications, this becomes automatic — Bob doesn't
          "think about" retrying anymore, it just happens.
        """
        ...

    def get_habituated_rules(self) -> list["ImprovementRule"]:
        """Return all habituated rules (for monitoring, not reflection)."""
        ...

    def is_habituated(self, rule_id: str) -> bool:
        """Check if a specific rule is habituated."""
        ...


class NightProcessor:
    """Replays daily episodes through 0.5B at high temperature during sleep hours.

    Runs during quiet_hours (default 23:00-07:00) when user is absent.
    Results are stored WITHOUT source attribution — they appear as
    "intuitions" or "hunches" rather than traceable conclusions.

    Inspired by memory consolidation during sleep: the brain replays
    daily experiences with random variations, strengthening important
    memories and finding new connections.
    """

    def __init__(
        self,
        llm_router: "LLMRouter",
        model_manager: "ModelManager",
        memory: "MemorySystem",
        inner_monologue: "InnerMonologue",
        priming_engine: ImplicitPrimingEngine,
        association_engine: LatentAssociationEngine,
        config: "NightProcessingConfig",
    ) -> None: ...

    async def run_nightly(self) -> list[NightProcessingResult]:
        """Run night processing cycle.

        Pre-conditions:
        1. Current time is within quiet_hours
        2. User is not present (world_state.user.present == false)
        3. ModelManager is in NORMAL profile (0.5B available)
        4. Not already running this cycle

        Steps:
        0. Suspend InnerMonologue (set activity to SUSPENDED via event bus).
           This ensures exclusive 0.5B access during night processing.
        1. Query today's episodic_log entries (SELECT ... WHERE date = today)
        2. Load thought summaries from InnerMonologue (snapshot before suspend)
        3. For each significant episode (mood_delta > 0.1 or goal event):
           a. Replay through 0.5B at temperature=config.night_processing.temperature (default 1.3)
           b. Generate "dreamy" variations and connections
           c. Extract insights (store WITHOUT attributing to night processing)
           d. If insight involves a sensory association:
              → create LatentAssociation (embedding + mood_delta)
           e. If insight suggests a behavioral prime:
              → create ImplicitPrime (trigger + context_fragment)
        4. Store results in sc_night_processing_log table
        5. Resume InnerMonologue (restore activity to LOW)
        6. Emit subconscious.night_completed event

        Resource constraints:
        - Max 0.5B calls per night: 50 (configured)
        - Max new primes per night: 5
        - Max new associations per night: 10
        - Yields between calls (asyncio.sleep) to not starve other tasks
        - InnerMonologue is SUSPENDED for the entire night processing
          duration (typically 5-15 minutes), then restored to LOW
        """
        ...

    def is_quiet_hours(self) -> bool:
        """Check if current time is within configured quiet hours."""
        ...

    def is_user_absent(self) -> bool:
        """Check world_state for user presence."""
        ...


class SubconsciousLayer:
    """Top-level orchestrator for all subconscious processes.

    Wraps around the conscious processing pipeline. When AgentRuntime
    prepares an LLM call, SubconsciousLayer:
    1. Pre-processes: applies habituated rules + implicit primes
    2. Passes to conscious processing (LLMRouter)
    3. Post-processes: checks for latent association triggers

    SubconsciousLayer is OPAQUE to ReflectionLoop — reflection can
    observe behavioral patterns but cannot introspect subconscious state.
    """

    def __init__(
        self,
        priming_engine: ImplicitPrimingEngine,
        association_engine: LatentAssociationEngine,
        habituation_engine: HabituationEngine,
        night_processor: NightProcessor,
        event_bus: "EventBus",
    ) -> None: ...

    async def pre_process(
        self, prompt: str, context: dict[str, Any], mood: "MoodState"
    ) -> tuple[str, dict[str, Any]]:
        """Enrich prompt and context with subconscious influences.

        Steps:
        1. Apply habituated rules to context
        2. Get applicable implicit primes for the situation
        3. Build implicit context and prepend to prompt
        4. Return modified (prompt, context)

        The modifications are NOT logged in a way accessible to reflection.
        Internal logging goes to sc_subconscious_log table (not in reflection queries).
        """
        ...

    async def post_process(
        self, response: str, embeddings: dict[str, np.ndarray]
    ) -> None:
        """Post-process after conscious response generation.

        Args:
            response: The generated response text.
            embeddings: Available embeddings keyed by source:
                - "visual": CLIP embedding from current camera frame (512-d float32)
                - "semantic": Sentence embedding of the response (384-d float32)
                - "audio": Prosodic feature vector from current utterance (6-d float32)
                Dict may be empty if no embeddings are available for this interaction.

        Steps:
        1. If visual/semantic embeddings are available for this interaction:
           a. Check latent associations for triggers (cosine similarity > threshold)
           b. Apply any triggered mood deltas (cause="natural_drift")
        2. Update activation counts for any primes used in pre_process
        """
        ...

    async def run_maintenance(self) -> None:
        """Periodic maintenance tasks.

        Called from heartbeat (every 30 sec):
        1. Check if quiet_hours → start night_processor if not running
        2. Check habituation_engine for newly habituated rules
        3. Decay stale primes
        4. Prune inactive latent associations
        """
        ...
```

**Configuration dataclass.**

```python
@dataclass
class ImplicitPrimingConfig:
    """ImplicitPrimingEngine sub-config."""
    max_active_primes: int = 20
    max_concurrent: int = 3
    min_strength: float = 0.1
    decay_after_activations: int = 100
    decay_rate: float = 0.01
    stale_days: int = 14


@dataclass
class LatentAssociationConfig:
    """LatentAssociationEngine sub-config."""
    faiss_path: str = "data/memory/latent_vectors"
    embedding_dim: int = 512
    similarity_threshold: float = 0.75
    max_mood_delta: float = 0.05
    max_associations: int = 500
    prune_inactive_days: int = 30


@dataclass
class HabituationConfig:
    """HabituationEngine sub-config."""
    threshold: int = 50
    check_interval_min: int = 60


@dataclass
class NightProcessingConfig:
    """NightProcessor sub-config."""
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"
    require_user_absent: bool = True
    temperature: float = 1.3
    max_calls_per_night: int = 50
    max_new_primes: int = 5
    max_new_associations: int = 10
    episode_significance_threshold: float = 0.1
    max_tokens_per_call: int = 256      # longer than InnerMonologue (64)
    inter_call_delay_sec: float = 10.0   # sleep between calls to not starve other tasks
    # Budget: 50 × (~1.5s generation + 10s sleep) ≈ 10 min (within 5-15 min range)


@dataclass
class SubconsciousConfig:
    """Top-level configuration for subconscious processing subsystem."""
    enabled: bool = True
    implicit_priming: ImplicitPrimingConfig = field(default_factory=ImplicitPrimingConfig)
    latent_associations: LatentAssociationConfig = field(default_factory=LatentAssociationConfig)
    habituation: HabituationConfig = field(default_factory=HabituationConfig)
    night_processing: NightProcessingConfig = field(default_factory=NightProcessingConfig)
```

**Configuration YAML.**

```yaml
# config/bob.yaml (addition)
subconscious:
  enabled: true
  implicit_priming:
    max_active_primes: 20               # maximum concurrent implicit primes
    max_concurrent: 3                    # max primes applied per single LLM call
    min_strength: 0.1                    # below this, prime is not applied
    decay_after_activations: 100        # start decaying strength after N activations
    decay_rate: 0.01                    # strength reduction per activation after threshold
    stale_days: 14                      # primes not activated in N days lose strength
  latent_associations:
    faiss_path: "data/memory/latent_vectors"
    embedding_dim: 512                  # matches CLIP output
    similarity_threshold: 0.75          # cosine similarity to trigger
    max_mood_delta: 0.05                # cap on any single mood shift from association
    max_associations: 500               # cap on total stored associations
    prune_inactive_days: 30
  habituation:
    threshold: 50                       # times_applied before rule becomes automatic
    check_interval_min: 60              # how often to check for new habituations
  night_processing:
    quiet_hours_start: "23:00"
    quiet_hours_end: "07:00"
    require_user_absent: true
    temperature: 1.3                    # high temperature for "dreamy" generation
    max_calls_per_night: 50             # 0.5B inference budget per night
    max_new_primes: 5                   # cap on new primes per night
    max_new_associations: 10            # cap on new associations per night
    episode_significance_threshold: 0.1 # min mood_delta to replay an episode
    inter_call_delay_sec: 2             # sleep between 0.5B calls (yield to other tasks)
```

**Events (additions to Event Catalog).**

| Event type | Publisher | Subscribers | Payload keys |
|------------|-----------|-------------|-------------|
| `subconscious.night_started` | NightProcessor | AgentRuntime | start_time, episodes_to_process |
| `subconscious.night_completed` | NightProcessor | AgentRuntime | duration_min, episodes_processed, primes_created, associations_created |
| `subconscious.rule_habituated` | HabituationEngine | AgentRuntime | rule_id, times_applied |
| `subconscious.prime_activated` | ImplicitPrimingEngine | (internal only) | prime_id, situation, strength |
| `subconscious.association_triggered` | LatentAssociationEngine | (internal only) | association_id, similarity, mood_delta |

Note: `prime_activated` and `association_triggered` events are emitted but NOT subscribed to by ReflectionLoop. They are only for internal analytics/monitoring.

**SQLite tables.**

```sql
-- Implicit primes (hidden context fragments)
CREATE TABLE sc_implicit_primes (
    id                  TEXT PRIMARY KEY,
    trigger_pattern     TEXT NOT NULL,
    context_fragment    TEXT NOT NULL,
    source              TEXT NOT NULL,       -- "latent_association", "night_processing", "habituation"
    strength            REAL NOT NULL DEFAULT 0.5,
    created_at          TEXT NOT NULL,
    last_activated      TEXT,
    activation_count    INTEGER DEFAULT 0,
    active              INTEGER DEFAULT 1
);

-- Latent associations (embedding-to-mood mappings)
CREATE TABLE sc_latent_associations (
    id                      TEXT PRIMARY KEY,
    embedding_type          TEXT NOT NULL,       -- "visual", "semantic"
    mood_delta_json         TEXT NOT NULL,       -- JSON dict: {"valence": 0.05, ...}
    similarity_threshold    REAL NOT NULL,
    faiss_index_id          INTEGER NOT NULL,    -- position in latent FAISS index
    created_at              TEXT NOT NULL,
    trigger_count           INTEGER DEFAULT 0,
    last_triggered          TEXT,
    active                  INTEGER DEFAULT 1
);

-- Night processing log
CREATE TABLE sc_night_processing_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_date        TEXT NOT NULL,
    insight             TEXT NOT NULL,
    primes_created      INTEGER DEFAULT 0,
    associations_created INTEGER DEFAULT 0,
    processed_at        TEXT NOT NULL,
    temperature         REAL NOT NULL,
    calls_used          INTEGER NOT NULL
);

-- Subconscious activity log (NOT queryable by ReflectionLoop)
CREATE TABLE sc_subconscious_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    event_type      TEXT NOT NULL,       -- "prime_activated", "association_triggered",
                                         -- "rule_habituated", "night_insight"
    details_json    TEXT NOT NULL,
    mood_effect_json TEXT                 -- optional mood delta applied
);

-- Note: improvement_rules.automatic column is defined in §3.4.4 canonical schema.

CREATE INDEX idx_primes_active ON sc_implicit_primes(active);
CREATE INDEX idx_primes_trigger ON sc_implicit_primes(trigger_pattern);
CREATE INDEX idx_latent_assoc_active ON sc_latent_associations(active);
CREATE INDEX idx_night_log_date ON sc_night_processing_log(episode_date);
CREATE INDEX idx_subconscious_log_ts ON sc_subconscious_log(timestamp);
```

**Memory budget impact.** Zero additional model memory — uses existing 0.5B model. Latent FAISS index: ~10 MB for 500 associations at 512 dimensions. Implicit primes: ~20 x 1 KB = ~20 KB. Night processing: no concurrent model load (runs during quiet hours when 0.5B is underutilized). Total additional RAM: ~10 MB. Negligible.

**Integration points.**

1. **AgentRuntime.__init__**: Add `subconscious: SubconsciousLayer` parameter. In the main event loop (step 4 of `run()`), wrap `content_guard.process()` calls:

```python
# Before:
response = await content_guard.process(prompt, context)

# After:
enriched_prompt, enriched_context = await subconscious.pre_process(prompt, context, mood)
# Note: ContentGuard processes the enriched prompt — implicit primes do NOT bypass
# safety filtering. If a prime injects unsafe content, ContentGuard catches it.
response = await content_guard.process(enriched_prompt, enriched_context)
await subconscious.post_process(response, current_embeddings)
```

2. **AgentRuntime.heartbeat()**: Call `subconscious.run_maintenance()` to check quiet hours, habituation, and decay.

3. **MoodEngine**: Latent association triggers call `MoodEngine.process_event()` with `cause="natural_drift"` — this is a deliberately vague cause that does not reveal the subconscious trigger. The mood_history table records it as a natural drift.

4. **ReflectionLoop**: All subconscious tables use `sc_` prefix (`sc_implicit_primes`, `sc_latent_associations`, `sc_night_processing_log`, `sc_subconscious_log`). ReflectionLoop accesses the database through `ScopedDBReader` (see below) with a TABLE_ALLOWLIST that **excludes all `sc_*` tables**. Any query referencing a `sc_*` table raises `AccessViolationError`. This is enforced at runtime — not just by convention. Additionally, ReflectionLoop does not receive a reference to SubconsciousLayer (architectural invariant verified by unit test and beadloom lint rule).

5. **SelfImprovement (section 3.3.4)**: Modify `improvement_rules` table to add `automatic INTEGER DEFAULT 0` column. `SelfImprovement.evaluate_rules()` now excludes `WHERE automatic = 1`. `HabituationEngine.check_habituation()` sets `automatic = 1` when `times_applied >= threshold`.

6. **InnerMonologue**: NightProcessor receives the InnerMonologue reference to access thought summaries for replay context. Night processing may generate new thoughts (stored in a separate night buffer, not the main ring buffer).

7. **VisualGrounding / SemanticMemory**: After new embeddings are created, SubconsciousLayer.post_process() checks them against latent associations via the LatentAssociationEngine.

**Development phase assignment.** Phase 6 (Self-improvement + Fine-tune). Subconscious processing is the most advanced cognitive mechanism and depends on all other systems being operational (mood, taste, reflection, inner monologue, memory, sensory grounding).

**New files for repository structure (section 11).**

```
src/bob/mind/subconscious.py              # SubconsciousLayer, ImplicitPrimingEngine, LatentAssociationEngine
src/bob/mind/habituation.py               # HabituationEngine
src/bob/mind/night_processor.py           # NightProcessor, NightProcessingResult
data/memory/latent_vectors/           # FAISS index for latent associations
tests/test_mind/test_subconscious.py
tests/test_mind/test_habituation.py
tests/test_mind/test_night_processor.py
```

---

### 3.4. Memory System

A four-level memory system.

#### 3.4.1. Overview

All memory subsystems use SQLite (`data/bob.db`) as the single storage backend.
FAISS provides in-process vector search for semantic memory embeddings;
metadata and facts are stored in SQLite alongside everything else.

```
┌─────────────────────────────────────────────────────────┐
│                    MEMORY SYSTEM                         │
│                                                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │  Episodic   │  │   Semantic   │  │   Structured   │  │
│  │  Memory     │  │   Memory     │  │   State        │  │
│  │             │  │              │  │                │  │
│  │  SQLite:    │  │  SQLite:     │  │  SQLite:       │  │
│  │  episodic_  │  │  semantic_   │  │  - goals       │  │
│  │  log table  │  │  memory tbl  │  │  - experience  │  │
│  │             │  │  + FAISS     │  │  - world state │  │
│  │  Structured │  │  (in-proc    │  │  - rules       │  │
│  │  daily      │  │   vectors)   │  │                │  │
│  │  entries    │  │  Embeddings: │  │                │  │
│  │             │  │  all-Mini    │  │                │  │
│  │             │  │  LM-L6-v2   │  │                │  │
│  └─────────────┘  └──────────────┘  └────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │              SOUL (template -> local)                │    │
│  │  bob-soul/ (template)  ->  data/soul/SOUL.md        │    │
│  │         (personality, values, evolution)             │    │
│  └──────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

#### 3.4.2. Episodic Memory

Structured daily log stored in SQLite (`episodic_log` table). Each entry represents
a notable event, interaction, or state change. Entries are structured for efficient
querying (by date, type, tags) while preserving rich text content for LLM context.

```python
class EpisodicMemory:
    """Episodic memory backed by SQLite.

    Stores daily events as structured rows. Supports:
    - Date-range queries (last N days)
    - Event-type filtering (interactions, reflections, goals)
    - Tag-based search
    - LLM-friendly formatting via format_as_markdown()
    """

    def __init__(self, db_path: str) -> None: ...

    async def log_event(
        self,
        event_type: str,
        title: str,
        content: str,
        mood_snapshot: "MoodState | None" = None,
        related_goal_id: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Log an episodic event. Returns row ID."""
        ...

    async def get_day_log(self, date: str) -> list[dict[str, Any]]:
        """Return all entries for a given date (YYYY-MM-DD)."""
        ...

    async def get_recent(self, days: int = 7) -> list[dict[str, Any]]:
        """Return entries from the last N days, ordered by timestamp."""
        ...

    async def search_by_type(
        self, event_type: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Find entries by event type."""
        ...

    async def search_by_tags(
        self, tags: list[str], limit: int = 50
    ) -> list[dict[str, Any]]:
        """Find entries matching any of the given tags."""
        ...

    def format_as_markdown(self, entries: list[dict[str, Any]]) -> str:
        """Format entries as Markdown text for LLM context injection.

        Output format (same human-readable style as before):

        # Bob's Diary — 2026-02-26

        ## Morning (06:00–12:00)

        ### 08:15 — User arrived
        - Presence detected (Vision -> person_detected)
        - Mood: upbeat (valence 0.55, social 0.50)

        Groups entries by time_of_day and formats as Markdown sections.
        """
        ...
```

**SQLite schema:** See section 3.4.4 for the canonical `episodic_log` table definition and indices.

**Example entries (equivalent to the former Markdown diary):**

| timestamp | date | time_of_day | event_type | title | content |
|-----------|------|-------------|------------|-------|---------|
| 2026-02-26T06:05:00 | 2026-02-26 | morning | wakeup | Waking up | Started heartbeat, all services OK. Room temperature: 22°C. User not detected. |
| 2026-02-26T08:15:00 | 2026-02-26 | morning | user_arrived | User arrived | Presence detected (Vision → person_detected). Greeted: "Good morning!" User replied: "Hi, Bob". |
| 2026-02-26T09:00:00 | 2026-02-26 | morning | goal_work | Working on G-042 | Goal: "Optimize voice pipeline". Latency analysis → avg 2.3 sec. Created sub-goal: "Try streaming TTS". |
| 2026-02-26T22:00:00 | 2026-02-26 | evening | reflection | Evening reflection | Productive day: 3 goals processed, 1 completed. Insight: cache frequent LLM requests. |

#### 3.4.3. Semantic Memory

Long-term semantic memory backed by SQLite (`semantic_memory` table) + FAISS
(in-process vector index). Facts and knowledge are stored as structured rows
with category, importance, and access tracking. FAISS provides cosine-similarity
search over embeddings; SQLite provides filtering by category and metadata.

```python
class SemanticMemory:
    """Semantic memory with FAISS (in-process) + SQLite metadata.

    Each memory entry is stored as a row in semantic_memory table with
    its embedding position in FAISS. Recall combines vector similarity
    (FAISS top-K) with optional category filtering (SQL WHERE).
    """

    def __init__(
        self,
        db_path: str,
        vector_db_path: str = "data/memory/vectors",
        embedding_model: str = "all-MiniLM-L6-v2",
    ) -> None: ...

    async def remember(self, text: str, category: str, metadata: dict[str, Any]) -> str:
        """Remember a new fact.

        Steps:
        1. Compute embedding via all-MiniLM-L6-v2
        2. Add to FAISS index → get faiss_index_id
        3. INSERT into semantic_memory table
        4. Return entry ID (UUID)
        """
        ...

    async def recall(
        self, query: str, top_k: int = 5, category: str | None = None
    ) -> list["MemoryEntry"]:
        """Find relevant memories.

        Steps:
        1. Compute query embedding
        2. FAISS search → top_k * 2 candidates (over-fetch for filtering)
        3. If category specified: filter by category in SQL
        4. Exclude outdated entries (outdated = 1)
        5. Update accessed_at and access_count for returned entries
        6. Return top_k MemoryEntry objects
        """
        ...

    async def forget(self, memory_id: str) -> None:
        """Soft-delete a memory (set outdated = 1).

        Embedding remains in FAISS (cleaned up during consolidate).
        """
        ...

    async def consolidate(self) -> None:
        """Consolidation: remove outdated entries from FAISS, deduplicate.

        Runs daily during reflection. Steps:
        1. Find all entries with outdated = 1
        2. Remove their embeddings from FAISS (rebuild index if > 10% stale)
        3. Delete outdated rows from SQLite
        4. Find near-duplicate entries (cosine > 0.95) → merge
        """
        ...

    def format_as_markdown(self, entries: list["MemoryEntry"]) -> str:
        """Format memory entries as Markdown for LLM context injection.

        Output format (grouped by category):

        ## User
        - Name: [name]
        - Prefers informal address

        ## Important facts
        - Mac mini sits on the desk

        ## Skills and rules
        - On API error — wait 30 sec and retry
        """
        ...
```

**SQLite schema:** See section 3.4.4 for the canonical `semantic_memory` table definition and indices.

**Example entries (equivalent to the former MEMORY.md):**

| id | text | category | importance | source |
|----|------|----------|------------|--------|
| mem-001 | User prefers Bob to use informal address | user | 0.8 | user_statement |
| mem-002 | Mac mini sits on the desk to the left of the monitor | environment | 0.6 | observation |
| mem-003 | On API error — wait 30 sec and retry (max 3 times) | rules | 0.9 | reflection |
| mem-004 | Do not disturb the user from 23:00 to 07:00 | rules | 0.9 | user_statement |

#### 3.4.4. Structured State (SQLite)

**Canonical source of truth for all 26 SQLite tables** used by Bob. Component
sections (§3.3.x) may reference these tables but do NOT duplicate the schema —
all CREATE TABLE and CREATE INDEX statements are defined here only.

```sql
-- GoalEngine: goals and dependencies (section 3.3.1)
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

-- TasteEngine: object experience and taste history (section 3.3.5)
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

-- MoodEngine: mood history (section 3.3.6)
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

-- Experience table (utility)
-- Owner: AgentRuntime — logs every action outcome for ReflectionLoop analysis
-- Writers: AgentRuntime (after each skill execution, LLM call, or goal step)
-- Readers: ReflectionLoop (via ScopedDBReader), SelfImprovement (lesson patterns)
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

-- World state table (utility, key-value store)
-- Owner: AgentRuntime — central key-value store for cross-component state
-- Writers: VisionService (user.present), TabletController (tablet.battery),
--          MoodEngine (bob.mood.*), WindowService (room.temperature)
-- Readers: NightProcessor (user.present), InnerMonologue (bob.energy),
--          any component via AgentRuntime.get_world_state(key)
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
    active              INTEGER DEFAULT 1,
    automatic           INTEGER DEFAULT 0   -- 1 = habituated (see 3.3.11 HabituationEngine)
);

-- Content safety violations (section 8.8)
-- Owner: ContentGuard.ViolationTracker — tracks content policy violations
-- Writers: ContentGuard (on each input/output violation detected)
-- Readers: ContentGuard (escalation tier calculation), RelationshipTracker (impact)
CREATE TABLE content_violations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    timestamp       TEXT NOT NULL,
    category        TEXT NOT NULL,       -- ViolationCategory enum value
    confidence      REAL NOT NULL,
    tier            INTEGER NOT NULL,    -- escalation tier at time of violation
    input_hash      TEXT NOT NULL,       -- SHA-256 hash (not raw text — privacy)
    guard_layer     TEXT NOT NULL        -- "input" | "output"
);

-- Episodic Memory: daily event log (section 3.4.2)
CREATE TABLE episodic_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,          -- ISO 8601
    date            TEXT NOT NULL,          -- YYYY-MM-DD (for grouping/indexing)
    time_of_day     TEXT NOT NULL,          -- "morning", "afternoon", "evening", "night"
    event_type      TEXT NOT NULL,          -- "wakeup", "user_arrived", "goal_work",
                                            -- "reflection", "interaction", "observation",
                                            -- "mood_change", "thought_summary"
    title           TEXT NOT NULL,          -- brief heading
    content         TEXT NOT NULL,          -- full entry text
    mood_json       TEXT,                   -- JSON snapshot of MoodState at entry time
    related_goal_id TEXT,                   -- FK to goals(id) if applicable
    tags_json       TEXT DEFAULT '[]'       -- JSON array of string tags
);

-- Semantic Memory: long-term facts with FAISS vectors (section 3.4.3)
CREATE TABLE semantic_memory (
    id              TEXT PRIMARY KEY,       -- UUID
    text            TEXT NOT NULL,          -- the fact / knowledge
    category        TEXT NOT NULL,          -- "user", "environment", "rules",
                                            -- "skills", "facts", "insights"
    faiss_index_id  INTEGER NOT NULL,       -- position in FAISS index
    importance      REAL NOT NULL DEFAULT 0.5,  -- 0.0 .. 1.0
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    accessed_at     TEXT NOT NULL,          -- last recall timestamp
    access_count    INTEGER DEFAULT 0,
    source          TEXT,                   -- "reflection", "user_statement",
                                            -- "observation", "genesis"
    outdated        INTEGER DEFAULT 0,     -- 1 = soft-deleted
    metadata_json   TEXT DEFAULT '{}'
);

-- Inner Monologue: thought summaries (section 3.3.8)
CREATE TABLE thought_summaries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    thought_count       INTEGER NOT NULL,
    dominant_topic      TEXT NOT NULL,
    avg_valence         REAL NOT NULL,
    avg_arousal         REAL NOT NULL,
    key_themes_json     TEXT NOT NULL,       -- JSON array of top tags
    sample_thoughts_json TEXT NOT NULL,      -- JSON array of representative thoughts
    mood_drift_json     TEXT NOT NULL        -- JSON dict of net mood deltas
);

-- Emergent Behavior: discovered taste axes (section 3.3.9)
CREATE TABLE discovered_axes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL,
    centroid_json   TEXT NOT NULL,         -- JSON array of floats
    member_count    INTEGER NOT NULL,
    discovered_at   TEXT NOT NULL,
    confidence      REAL NOT NULL,
    source_axes_json TEXT NOT NULL,        -- JSON array of axis names
    integrated      INTEGER DEFAULT 0,    -- 1 if added to TasteProfile
    active          INTEGER DEFAULT 1
);

-- Emergent Behavior: mood-taste correlations (section 3.3.9)
CREATE TABLE cross_domain_associations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mood_dimension  TEXT NOT NULL,
    taste_axis      TEXT NOT NULL,
    correlation     REAL NOT NULL,
    sample_count    INTEGER NOT NULL,
    discovered_at   TEXT NOT NULL,
    last_validated  TEXT NOT NULL,
    active          INTEGER DEFAULT 1,
    UNIQUE(mood_dimension, taste_axis)
);

-- Emergent Behavior: MoodPredictor state (section 3.3.9)
CREATE TABLE mood_predictor_state (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton row
    start_date      TEXT NOT NULL,
    current_alpha   REAL NOT NULL DEFAULT 0.0,
    learned_event_count INTEGER NOT NULL DEFAULT 0,
    last_retrained_at TEXT,
    last_validation_mae REAL,
    model_version INTEGER NOT NULL DEFAULT 0
);

-- Sensory Grounding: visual embeddings metadata (section 3.3.10)
CREATE TABLE visual_embeddings (
    id              TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL,
    source          TEXT NOT NULL,         -- "snapshot", "object_crop", "scene"
    metadata_json   TEXT DEFAULT '{}',
    faiss_index_id  INTEGER NOT NULL       -- position in FAISS index
);

-- Sensory Grounding: links between visual embeddings and memory entries (section 3.3.10)
CREATE TABLE visual_memory_links (
    visual_embedding_id TEXT NOT NULL REFERENCES visual_embeddings(id),
    memory_entry_id     TEXT NOT NULL,     -- ID in semantic memory or episodic log
    memory_type         TEXT NOT NULL,     -- "semantic", "episodic"
    created_at          TEXT NOT NULL,
    PRIMARY KEY (visual_embedding_id, memory_entry_id)
);

-- Sensory Grounding: audio prosodic features (section 3.3.10)
CREATE TABLE prosodic_features (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    pitch_mean      REAL NOT NULL,
    pitch_variance  REAL NOT NULL,
    energy_mean     REAL NOT NULL,
    speech_rate     REAL NOT NULL,
    pause_ratio     REAL NOT NULL,
    duration_sec    REAL NOT NULL,
    engagement      REAL NOT NULL,
    urgency         REAL NOT NULL,
    calmness        REAL NOT NULL
);

-- Sensory Grounding: learned circadian pattern (section 3.3.10)
CREATE TABLE circadian_patterns (
    id              INTEGER PRIMARY KEY CHECK (id = 1),  -- singleton
    hour_activity_json  TEXT NOT NULL,     -- JSON array of 24 floats
    hour_valence_json   TEXT NOT NULL,     -- JSON array of 24 floats
    hour_social_json    TEXT NOT NULL,     -- JSON array of 24 floats
    learned_from_days   INTEGER NOT NULL,
    last_updated        TEXT NOT NULL
);

-- Sensory Grounding: raw DoA observations (section 3.3.10)
-- Owner: SpatialGrounding | Readers: SpatialGrounding.cluster_directions()
CREATE TABLE doa_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    direction_deg   REAL NOT NULL,
    event_type      TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0
);

-- Sensory Grounding: spatial locations from DoA (section 3.3.10)
CREATE TABLE spatial_locations (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    direction_deg   REAL NOT NULL,
    direction_spread REAL NOT NULL,
    event_count     INTEGER NOT NULL DEFAULT 0,
    last_heard      TEXT NOT NULL,
    semantic_tags_json TEXT DEFAULT '[]'
);

-- Subconscious: implicit primes (section 3.3.11)
CREATE TABLE sc_implicit_primes (
    id                  TEXT PRIMARY KEY,
    trigger_pattern     TEXT NOT NULL,
    context_fragment    TEXT NOT NULL,
    source              TEXT NOT NULL,       -- "latent_association", "night_processing", "habituation"
    strength            REAL NOT NULL DEFAULT 0.5,
    created_at          TEXT NOT NULL,
    last_activated      TEXT,
    activation_count    INTEGER DEFAULT 0,
    active              INTEGER DEFAULT 1
);

-- Subconscious: latent associations (section 3.3.11)
CREATE TABLE sc_latent_associations (
    id                      TEXT PRIMARY KEY,
    embedding_type          TEXT NOT NULL,       -- "visual", "semantic"
    mood_delta_json         TEXT NOT NULL,       -- JSON dict: {"valence": 0.05, ...}
    similarity_threshold    REAL NOT NULL,
    faiss_index_id          INTEGER NOT NULL,    -- position in latent FAISS index
    created_at              TEXT NOT NULL,
    trigger_count           INTEGER DEFAULT 0,
    last_triggered          TEXT,
    active                  INTEGER DEFAULT 1
);

-- Subconscious: night processing log (section 3.3.11)
CREATE TABLE sc_night_processing_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_date        TEXT NOT NULL,
    insight             TEXT NOT NULL,
    primes_created      INTEGER DEFAULT 0,
    associations_created INTEGER DEFAULT 0,
    processed_at        TEXT NOT NULL,
    temperature         REAL NOT NULL,
    calls_used          INTEGER NOT NULL
);

-- Subconscious: activity log — NOT queryable by ReflectionLoop (section 3.3.11)
CREATE TABLE sc_subconscious_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    event_type      TEXT NOT NULL,       -- "prime_activated", "association_triggered",
                                         -- "rule_habituated", "night_insight"
    details_json    TEXT NOT NULL,
    mood_effect_json TEXT                 -- optional mood delta applied
);

CREATE INDEX idx_goals_status ON goals(status);
CREATE INDEX idx_goals_parent ON goals(parent_id);
CREATE INDEX idx_goals_priority ON goals(priority);
CREATE INDEX idx_obj_exp_object ON object_experience(object_id);
CREATE INDEX idx_obj_exp_action ON object_experience(action);
CREATE INDEX idx_taste_history_axis ON taste_history(axis);
CREATE INDEX idx_taste_history_ts ON taste_history(timestamp);
CREATE INDEX idx_mood_timestamp ON mood_history(timestamp);
CREATE INDEX idx_mood_primary ON mood_history(primary_mood);
CREATE INDEX idx_experience_action ON experience(action_type, action_name);
CREATE INDEX idx_experience_success ON experience(success);
CREATE INDEX idx_world_state_updated ON world_state(updated_at);
CREATE INDEX idx_violations_user_time ON content_violations(user_id, timestamp);
CREATE INDEX idx_episodic_date ON episodic_log(date);
CREATE INDEX idx_episodic_type ON episodic_log(event_type);
CREATE INDEX idx_episodic_ts ON episodic_log(timestamp);
CREATE INDEX idx_semantic_category ON semantic_memory(category);
CREATE INDEX idx_semantic_outdated ON semantic_memory(outdated);
CREATE INDEX idx_semantic_importance ON semantic_memory(importance);
CREATE INDEX idx_thought_sum_period ON thought_summaries(period_start);
CREATE INDEX idx_discovered_axes_active ON discovered_axes(active);
CREATE INDEX idx_cross_domain_active ON cross_domain_associations(active);
CREATE INDEX idx_visual_embed_ts ON visual_embeddings(timestamp);
CREATE INDEX idx_visual_links_memory ON visual_memory_links(memory_entry_id);
CREATE INDEX idx_prosodic_ts ON prosodic_features(timestamp);
CREATE INDEX idx_spatial_dir ON spatial_locations(direction_deg);
CREATE INDEX idx_primes_active ON sc_implicit_primes(active);
CREATE INDEX idx_primes_trigger ON sc_implicit_primes(trigger_pattern);
CREATE INDEX idx_latent_assoc_active ON sc_latent_associations(active);
CREATE INDEX idx_night_log_date ON sc_night_processing_log(episode_date);
CREATE INDEX idx_subconscious_log_ts ON sc_subconscious_log(timestamp);
```

#### 3.4.5. SOUL — Bob's modular "soul"

SOUL templates live in the `bob-soul/` directory within the main repository
(licensed under CC BY-NC-SA 4.0, see LICENSE-CC-BY-NC-SA.md).
They define Bob's initial personality: character, style, values, and serve as
a **single starting point** for all instances.

**Philosophy (inspired by the book):** in "We Are Legion (We Are Bob)" each copy of Bob
starts with the same "genome," but over time becomes a unique
personality. Our approach is analogous:

1. `bob-soul/` (template directory) — the **initial genome**, identical for all.
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
bob-soul/                           # Initial personality "genome" (CC BY-NC-SA 4.0)
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

    async def genesis(self) -> dict[str, Any]:
        """First launch: generate a unique personality.

        1. Load the template from bob-soul/ directory
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
        - book_reference_probability decreases with archetype drift:
          awakening ~0.35, week 2 ~0.15, month+ ~0.05 (own jokes replace book refs)
        - Tastes evolve through TasteEvolution (conviction grows with experience)
        - Mood is updated through MoodEngine (baseline can shift)
        """
        ...
```

### 3.5. Peripheral Services

#### 3.5.1. Vision Service

Capturing images from the OBSBOT camera and analyzing them.

**Threading strategy:** Runs in the main process. Camera capture (`cv2.VideoCapture.read`)
is offloaded via `asyncio.to_thread` (I/O-bound). YOLOv8n inference is offloaded to a
dedicated `ThreadPoolExecutor(max_workers=1)` to avoid blocking the event loop. At the
default 5-second snapshot interval, GIL contention is negligible (~50-100ms per cycle).
If OpenCV stability becomes an issue, the service can be extracted into a separate process
without API changes (EventBus abstraction).

```python
import numpy as np

@dataclass
class VisionEvent:
    timestamp: datetime
    event_type: str             # "person_detected", "person_left",
                                # "gesture_detected", "scene_changed"
    confidence: float
    details: dict[str, Any]     # depends on event_type

class VisionService:
    """Computer vision service.

    Runs in main process using thread pool for blocking operations.
    """

    def __init__(
        self,
        camera_index: int = 0,
        snapshot_interval_sec: float = 5.0,
        model: str = "yolov8n",         # or CLIP for scene description
        inference_workers: int = 1,     # ThreadPoolExecutor size
    ) -> None: ...

    async def run(self) -> None:
        """Main loop: capture (to_thread) -> analyze (executor) -> emit events."""
        ...

    async def capture_snapshot(self) -> np.ndarray:
        """Capture a frame from the camera via asyncio.to_thread."""
        ...

    async def analyze_frame(self, frame: np.ndarray) -> list[VisionEvent]:
        """Analyze a frame in ThreadPoolExecutor.

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
  inference_workers: 1              # ThreadPoolExecutor size for YOLOv8n
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
from collections.abc import AsyncIterator

class VoiceBridge:
    """Voice bridge: STT (Whisper.cpp) + TTS (Qwen3-TTS).

    Language is configured globally via config/bob.yaml and propagated
    to STT/TTS engines. Qwen3-TTS supports 10 languages natively:
    en, ru, zh, ja, ko, de, fr, pt, es, it.
    """

    def __init__(
        self,
        stt_model: str = "whisper-small",
        tts_model: str = "Qwen3-TTS-0.6B",
        tts_voice_ref: str | None = None,   # path to reference audio for cloning
        tts_voice_design: str | None = None, # text description: "male, calm, warm"
        tts_speed: float = 1.0,
        language: str = "en",
    ) -> None: ...

    async def transcribe(self, audio: bytes, language: str | None = None) -> str:
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

    async def send_command(self, command: str, params: dict[str, Any]) -> dict[str, Any]:
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
from collections.abc import Callable

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

### 3.6. Bootstrap and First Launch Setup

Bob requires several external dependencies (Ollama, models, optionally Claude
Code CLI). The bootstrap system handles first-launch detection and guided setup.

**Installation:** `pip install -e .` (or `uv pip install -e .`) — installs the
`bob` package and CLI entry points.

**Entry point:** `bob setup` command (or `python scripts/bootstrap.py`).

#### Prerequisites Check

The bootstrap wizard checks for required and optional components:

```python
@dataclass
class Prerequisite:
    name: str
    check_command: str               # Shell command to verify presence
    required: bool                   # False = optional, Bob works without it
    auto_install: str | None         # Install command (None = manual only)
    min_version: str | None          # Minimum version (semver)

PREREQUISITES: list[Prerequisite] = [
    Prerequisite(
        name="Python",
        check_command="python3 --version",
        required=True,
        auto_install=None,           # Must be pre-installed
        min_version="3.12.0",
    ),
    Prerequisite(
        name="Ollama",
        check_command="ollama --version",
        required=True,
        auto_install="brew install ollama",
        min_version="0.3.0",
    ),
    Prerequisite(
        name="Claude Code CLI",
        check_command="claude --version",
        required=False,              # Bob works without it (degraded)
        auto_install=None,           # Manual installation only
        min_version=None,
    ),
    Prerequisite(
        name="ADB",
        check_command="adb --version",
        required=False,              # Only for tablet deployment
        auto_install="brew install android-platform-tools",
        min_version=None,
    ),
    Prerequisite(
        name="Stable Diffusion (MLX)",
        check_command="python3 -c 'import mlx'",
        required=False,              # Only for visual asset generation
        auto_install="pip install mlx mlx-image",
        min_version=None,
    ),
]
```

#### Auto-Install Flow

For prerequisites with `auto_install` set, Bob asks permission before installing:

```
$ pip install -e .           # or: uv pip install -e .
$ bob setup

[1/7] Checking prerequisites...
  ✓ Python 3.12.4
  ✗ Ollama — not found
  ✗ Claude Code CLI — not found (optional)
  ✓ ADB 35.0.1

Ollama is required. Install via `brew install ollama`? [Y/n] y
  Installing Ollama...
  ✓ Ollama 0.5.1 installed

[2/7] Pulling required models...
  Pulling qwen2.5:7b-instruct-q4_K_M (4.4 GB)... [████████░░] 80%
  Pulling qwen2.5:0.5b-instruct-q8_0 (0.5 GB)... done

Claude Code CLI is optional (enables self-development, deep reflection).
Install manually: https://docs.anthropic.com/claude-code
Bob will work without it — complex tasks will use local LLM instead.

[3/7] Stable Diffusion for visual asset generation...
  Installing MLX image pipeline... done
  Downloading SDXL base model (6.2 GB)... [████████░░] 80%
  ✓ Stable Diffusion ready (assets will be AI-generated during Genesis)

[4/7] Verifying bob-soul templates...
  Checking bob-soul/ directory...
  ✓ bob-soul templates found
  ✓ Templates verified: archetype.md, awakening_script.md, taste_axes_pool.yaml

[5/7] Telegram bot configuration...
  Bob communicates via Telegram. You need a bot token.
  Create one: open Telegram → @BotFather → /newbot → copy token.
  Paste bot token: <token>
  ✓ Bot verified: @my_bob_bot

[6/7] Geolocation (for weather in Bob's window)...
  Auto-detected timezone: Europe/Berlin → lat=52.52, lon=13.41
  Use this location? [Y/n] y
  ✓ Geolocation configured

[7/7] Detecting hardware...
  ✓ Tablet detected: Samsung Galaxy Tab S9 (via ADB)
  ✓ Camera detected: OBSBOT Tiny 2
  ✗ Microphone: not found (voice input disabled, Telegram still works)

Setup complete! Run `bob start` to launch.
```

#### Graceful Degradation

| Component | Without it | Impact |
|-----------|-----------|--------|
| **Ollama** | Cannot start | Required — no LLM = no reasoning |
| **Telegram bot token** | Cannot start | Required — primary communication channel for Genesis and daily use |
| **bob-soul templates** | Cannot run Genesis | Required — templates for awakening, archetype, taste axes |
| **Claude Code CLI** | Fully functional, reduced capabilities | No self-development, lighter reflections, no code writing |
| **Stable Diffusion (MLX)** | No visual asset generation | Cannot generate avatar/room sprites; tablet remains dark or uses placeholder visuals |
| **ADB** | No tablet deployment | Avatar not displayed; Bob works headlessly |
| **Android tablet** | No visual presence | Bob operates via Telegram + voice only (headless mode) |
| **Camera (OBSBOT)** | No vision | Bob cannot see the user; audio-only interaction |
| **Microphone (ReSpeaker)** | No voice | Text-only via Telegram |
| **Geolocation** | No weather in window | WindowService shows time of day only, no weather data |

#### Configuration

```yaml
# config/bootstrap.yaml
bootstrap:
  completed: false                    # Set to true after first successful setup
  completed_at: null                  # ISO timestamp
  components:
    ollama:
      installed: false
      models_pulled: []
    claude_code:
      installed: false
      version: null
    stable_diffusion:
      installed: false
      model_downloaded: false
      model_name: "sdxl-base"
      lora_trained: false
    adb:
      installed: false
    bob_soul:
      initialized: false             # bob-soul/ directory verified
      templates_verified: false       # Required template files present
    telegram:
      configured: false
      bot_username: null              # e.g., "my_bob_bot"
      # Token stored in config/bob.yaml (not here — security)
  geolocation:
    timezone: null                    # Auto-detected from system (e.g., "Europe/Moscow")
    lat: null                         # Latitude for weather
    lon: null                         # Longitude for weather
    source: null                      # "auto" | "manual"
  hardware:
    camera_detected: false
    microphone_detected: false
    tablet_connected: false
```

#### BootstrapWizard Interface

```python
class BootstrapWizard:
    """First-launch setup wizard."""

    async def run(self) -> BootstrapResult:
        """Run the full bootstrap flow.

        1. Check all prerequisites (Python, Ollama, ADB, etc.)
        2. Offer to install missing required components
        3. Pull Ollama models (Qwen2.5-7B, Qwen2.5-0.5B)
        4. Install Stable Diffusion pipeline + download base model
        5. Verify bob-soul templates (check directory and required files)
        6. Configure Telegram bot token (create via @BotFather)
        7. Detect geolocation (auto from system timezone, or manual)
        8. Detect hardware (camera, mic)
        9. Detect Android tablet via ADB
        10. Write bootstrap.yaml with results
        11. Return summary
        """
        ...

    async def check_prerequisites(self) -> list[PrerequisiteStatus]: ...
    async def install_ollama(self) -> bool: ...
    async def pull_models(self, models: list[str]) -> dict[str, bool]: ...
    async def setup_stable_diffusion(self) -> bool:
        """Install MLX pipeline and download SD base model (~6 GB)."""
        ...
    async def verify_bob_soul(self) -> bool:
        """Verify bob-soul template directory.

        Checks that bob-soul/ directory exists and contains required
        template files: archetype.md, awakening_script.md,
        taste_axes_pool.yaml, room_prompts.md.
        """
        ...
    async def configure_telegram(self) -> str | None:
        """Configure Telegram bot token.

        If token not present in config/bob.yaml:
        1. Print instructions: create bot via @BotFather
        2. Prompt user for token
        3. Validate via Telegram getMe API call
        4. Write to config/bob.yaml and bootstrap.yaml
        Returns bot username on success, None if skipped.
        """
        ...
    async def detect_geolocation(self) -> dict[str, Any] | None:
        """Detect geolocation for WindowService weather.

        Auto-detection: read system timezone (/etc/localtime) → map to
        approximate lat/lon. User can override with city name or coordinates.
        If skipped, WindowService shows time without weather data.
        """
        ...
    async def detect_hardware(self) -> HardwareStatus: ...
    async def detect_tablet(self) -> TabletStatus:
        """Check for Android tablet via ADB. Prompt user to connect if not found."""
        ...
    async def is_setup_complete(self) -> bool:
        """Check if bootstrap has already been completed."""
        ...
```

**Setup state persistence:** The `bootstrap.yaml` file persists setup state
so that the wizard doesn't repeat on every launch. The wizard runs only when
`bootstrap.completed` is `false` or the file doesn't exist.

### 3.7. Startup Flow

The `bob start` command is the single entry point for running Bob. It handles
three scenarios: first-time setup, first-time awakening (Genesis), and normal
operation.

```
$ bob start
      │
      ▼
┌──────────────────────────────┐
│  bootstrap.yaml exists       │
│  AND bootstrap.completed?    │
└──────────┬───────────────────┘
           │ No
           ├──────────────────────────────┐
           │                              ▼
           │               ┌──────────────────────────┐
           │               │  Run BootstrapWizard      │
           │               │  (bob setup — 11 steps)   │
           │               └──────────┬───────────────┘
           │                          │ Done
           │◄─────────────────────────┘
           │ Yes
           ▼
┌──────────────────────────────┐
│  data/soul/SOUL.md exists?   │
└──────────┬───────────────────┘
           │ No
           ├──────────────────────────────┐
           │                              ▼
           │               ┌──────────────────────────┐
           │               │  Run GenesisMode.run()    │
           │               │  (9 stages: CONSCIOUSNESS │
           │               │   → WRITING TO SOUL)      │
           │               │  Duration: 40-60 min      │
           │               └──────────┬───────────────┘
           │                          │ SOUL.md created
           │◄─────────────────────────┘
           │ Yes
           ▼
┌──────────────────────────────┐
│  Initialize AgentRuntime     │
│  ├── Load SOUL.md            │
│  ├── Load config/*.yaml      │
│  ├── Connect EventBus        │
│  ├── Start LLMRouter         │
│  ├── Discover SkillDomains   │
│  ├── Connect peripherals     │
│  └── Start heartbeat loop    │
└──────────────────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  AgentRuntime.run()          │
│  (heartbeat every ~30 sec)   │
│                              │
│  Observe → Decide → Act      │
│       → Reflect → Evolve     │
└──────────────────────────────┘
```

```python
async def main() -> None:
    """Bob's entry point (bob start)."""

    # 1. Bootstrap check
    wizard = BootstrapWizard()
    if not await wizard.is_setup_complete():
        await wizard.run()

    # 2. Genesis check (including interrupted Genesis recovery)
    soul_path = Path("data/soul/SOUL.md")
    progress_path = Path("data/genesis_progress.json")

    if not soul_path.exists():
        genesis = GenesisMode()
        if progress_path.exists():
            # Interrupted Genesis — offer resume or restart
            await genesis.resume_or_restart(progress_path)
        else:
            await genesis.run()

    # 3. Normal operation
    runtime = await AgentRuntime.from_config("config/bob.yaml")
    await runtime.run()
```

**Restart behavior:** If Bob's process is killed and restarted, the same logic
applies — bootstrap is already complete, SOUL.md exists, so Bob enters normal
mode immediately. If Genesis was interrupted, Bob offers to resume from the
last completed stage (see section 5.1.1 for details). No data is lost (state
is persisted in SQLite + YAML + JSON files).

### 3.8. Configuration Loading and Error Handling

#### 3.8.1. Configuration Loading Order

Bob uses multiple YAML configuration files. They are loaded in a defined
order with clear override precedence.

**Loading order (later overrides earlier):**

```
1. Defaults (hardcoded in Python dataclasses)
2. config/bob.yaml          ← core settings
3. config/llm.yaml          ← LLM/Ollama/Claude Code
4. config/voice.yaml        ← STT/TTS/audio
5. config/vision.yaml       ← camera/YOLO
6. config/security.yaml     ← permissions/rate limits
7. config/bootstrap.yaml    ← first-launch state (read-only after setup)
8. src/bob/skills/*/config.yaml ← per-domain settings
9. Environment variables    ← BOB_LANGUAGE=ru, BOB_LLM_MODEL=...
10. CLI arguments           ← bob start --language=ru
```

**Variable substitution:** YAML files support `${bob.language}` syntax to
reference values from `bob.yaml`. Resolution happens at load time.

```python
class ConfigLoader:
    """Loads and merges configuration from multiple YAML files."""

    def __init__(self, config_dir: Path = Path("config")) -> None: ...

    def load(self) -> dict[str, Any]:
        """Load all configs in defined order, merge, and resolve variables.

        1. Load each YAML file in order
        2. Deep-merge (later values override earlier)
        3. Resolve ${...} variable references
        4. Apply environment variable overrides (BOB_ prefix)
        5. Apply CLI argument overrides
        6. Validate required fields
        """
        ...
```

#### 3.8.2. Error Handling Strategy

Bob uses three resilience patterns based on error type:

| Pattern | When | Behavior |
|---------|------|----------|
| **Retry** | Transient failures (network, SD generation) | Retry N times with backoff, then fail gracefully |
| **Circuit Breaker** | Degraded service (Ollama unresponsive) | After N failures, stop trying for cooldown period |
| **Graceful Degradation** | Component offline (no tablet, no camera) | Continue with reduced functionality |

**Per-component error strategy:**

| Component | Error type | Strategy | Fallback |
|-----------|-----------|----------|----------|
| Ollama 7B | Unresponsive | Circuit breaker (3 fails, 60s cooldown) | Use Qwen2.5-0.5B |
| Ollama 0.5B | Unresponsive | Retry 3x, 2s backoff | Log error, queue task |
| Claude Code CLI | Unavailable | Queue task (see 4.2.1) | Reflect with local LLM |
| Stable Diffusion | Generation fail | Retry 3x (see 5.4.2) | Use placeholder assets |
| WebSocket (tablet) | Disconnect | Reconnect with backoff (see 5.4.2b) | Headless mode |
| Telegram API | Network error | Retry 3x, 5s backoff | Queue messages |
| Camera/VisionService | Device lost | Retry on next scan cycle | Operate without vision |
| STT (Whisper) | Transcription fail | Retry 1x | Ask user to repeat |

**Circuit breaker implementation:**

```python
class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

@dataclass
class CircuitBreaker:
    """Prevents cascading failures by temporarily disabling a service."""

    failure_threshold: int = 3        # failures before opening circuit
    cooldown_sec: float = 60.0        # time before retrying
    _failure_count: int = field(init=False, default=0)
    _state: CircuitState = field(init=False, default=CircuitState.CLOSED)
    _last_failure: datetime | None = field(init=False, default=None)

    def record_failure(self) -> None: ...
    def record_success(self) -> None: ...
    def can_execute(self) -> bool: ...
```

#### 3.8.3. Update Mechanism

Bob updates via `bob update` — a managed pipeline that pulls code, installs
dependencies, runs migrations, and restarts the process.

```python
class UpdateManager:
    """Manages Bob's code updates."""

    async def check_for_updates(self) -> UpdateInfo | None:
        """Check remote for new commits (git fetch --dry-run).
        Called once per day by the scheduler.
        If updates available, notify user via Telegram.
        """
        ...

    async def update(self, target: str = "latest") -> UpdateResult:
        """Execute the update pipeline.

        Steps:
        1. Backup: snapshot current state (config, DB, data/soul/)
        2. Pull: git pull origin main (or target tag/commit)
        3. Dependencies: uv sync (install/update Python packages)
        4. Migrations: run DB migrations (alembic upgrade head)
        5. Config merge: validate new config against existing, warn on conflicts
        6. Restart: graceful shutdown + re-launch via process manager
        """
        ...

    async def rollback(self) -> None:
        """Rollback to pre-update state.
        Command: bob update --rollback
        Restores: git checkout, uv sync, DB rollback, config restore.
        """
        ...
```

**Update notification flow:**

```
Scheduler (daily, 09:00)
  │
  ├─ git fetch → new commits detected
  │
  ├─ Bob notifies user (Telegram):
  │   "There's a new update available (v0.2.1 → v0.3.0).
  │    Changes: <brief summary from CHANGELOG.md>
  │    Want me to update?"
  │
  ├─ User approves → bob update
  │   (CONFIRM-level approval, see 8.3)
  │
  └─ User declines → remind in 7 days
```

**Self-update via Claude Code CLI:** Bob can propose code changes through
Claude Code (section 4.2), but self-authored changes follow the normal
approval workflow (section 8.3, CONFIRM level). Bob cannot auto-deploy
his own code changes without user consent.

**Configuration:**

```yaml
# config/bob.yaml (addition)
update:
  check_interval_hours: 24
  check_time: "09:00"
  auto_check: true                   # check for updates automatically
  auto_update: false                 # never auto-update without user consent
  remind_interval_days: 7            # re-remind about skipped updates
  backup_before_update: true
  backup_dir: "data/backups/"
```

#### 3.8.4. User Settings Interface

Users configure Bob through natural conversation and Telegram commands.
There is no separate settings UI — Bob *is* the interface.

**Telegram commands:**

```
/settings                   — show current settings overview
/settings <category>        — show specific category
/settings <key> <value>     — set a value directly

Examples:
/settings notifications     — show notification preferences
/settings quiet_hours 23:00-08:00
/settings language ru
/settings autonomy high     — reduce confirmation prompts
```

**Conversational settings:** Users can also configure Bob through natural
language: *"Bob, don't message me after 11 PM"* — Bob parses the intent,
maps to `quiet_hours`, and confirms the change.

**Settings categories:**

| Category | Keys | Decision zone |
|----------|------|--------------|
| **Notifications** | quiet_hours, channels, urgency_threshold | USER_DOMAIN |
| **Autonomy** | approval_level (low/medium/high), auto_update | USER_DOMAIN |
| **Display** | language (en/ru), animation_speed, theme | SHARED_SPACE |
| **Privacy** | camera_enabled, data_retention_days, analytics | USER_DOMAIN |
| **Audio** | volume, tts_voice, audio_routing (tablet/local/both) | USER_DOMAIN |

**Decision zone interaction:** Settings in USER_DOMAIN are always accepted.
Settings in SHARED_SPACE (display theme, animation speed) go through
NegotiationEngine — Bob may suggest alternatives if the choice conflicts
with his aesthetic preferences.

**Persistence:**

```python
@dataclass
class UserSettings:
    """User-configurable settings with dataclass validation."""

    quiet_hours: tuple[time, time] | None = None
    language: str = "en"
    approval_level: str = "medium"        # low | medium | high
    camera_enabled: bool = True
    audio_routing: str = "tablet"         # tablet | local | both
    data_retention_days: int = 365
    animation_speed: float = 1.0

    def apply_from_natural_language(self, parsed_intent: dict[str, Any]) -> str:
        """Apply a setting change from parsed user intent.
        Returns confirmation message for the user.
        """
        ...
```

**Storage:** `data/user_settings.yaml`, loaded at startup, saved on change.

---

## 4. LLM Layer

### 4.1. Local Models via Ollama

All local models run through [Ollama](https://ollama.com/), which provides
a unified HTTP API and simple model management.

| Model | Role | Parameters | Quantization | RAM | Latency |
|-------|------|------------|--------------|-----|---------|
| Qwen2.5-7B | Main reasoning, dialogue, planning | 7B | Q4_K_M | ~4.4 GB¹ | ~1-2 sec |
| Qwen2.5-0.5B | Router/classifier, quick decisions | 0.5B | Q8_0 | ~0.5 GB | ~0.1-0.3 sec |

¹ Model weights in Q4_K_M quantization. Ollama runtime overhead (KV cache, buffers)
adds ~0.5 GB depending on context length, accounted for in ModelManager memory budget.

**Rationale for choosing Qwen2.5:**
- Excellent quality/size ratio for reasoning
- Strong multilingual support (English, Russian, Chinese, and others)
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

#### 4.2.1. Claude Code Permission Model

Bob and the user share a **Claude subscription** but work on **separate machines**
(Bob on his Mac Mini, user on their own device). There is no process-level
conflict — the coordination is social: Bob asks permission before using
the shared quota.

> **Scope split:** This section covers the *usage workflow* — permission flow,
> voice→Telegram escalation, degradation, and task queue. The *security mechanism*
> (`ClaudeCodeCoordinator` class, `QuotaTracker`, Negotiation Engine integration)
> lives in section 8.4.

**Core concept:** `ClaudeCodeCoordinator` (see section 8.4 for implementation)
manages permission requests and quota tracking. Before every CLI invocation,
Bob must obtain user permission via voice or Telegram.

**Permission flow:**

```
Bob needs Claude Code for a task
  │
  ├─ 1. Check QuotaTracker: is quota likely available?
  │     • If recently hit 429 → DEFER (no point asking)
  │     • If local call count near limit → warn user in request
  │
  ├─ 2. Check camera: is user nearby?
  │     ├─ User visible → ask via VOICE:
  │     │   "I need to refactor module X, can I use Claude Code?
  │     │    Should take about 15 minutes."
  │     │   ├─ Voice response within 10-20 sec → proceed/defer
  │     │   └─ No response → escalate to Telegram (step 3)
  │     │
  │     └─ User not visible → still ask via VOICE (might be nearby)
  │         ├─ Voice response → proceed/defer
  │         └─ No response within 10-20 sec → escalate to Telegram (step 3)
  │
  ├─ 3. TELEGRAM: send permission request with task description
  │     "I need to work on X (~15 min). Can I use Claude Code?"
  │     ├─ "Yes" / "Go ahead" → acquire → work → notify completion
  │     ├─ "No, I'm using it" → DEFER + "Let me know when you're done"
  │     ├─ "Not now" → DEFER + schedule retry
  │     └─ No response → DEFER to idle activities
  │
  └─ 4. IDLE while waiting:
        • Read/study (book references, code exploration)
        • Reflect using local LLM (Qwen2.5-7B)
        • Organize goals, review memory
        • Idle animations on tablet (reading, thinking)
        • Periodically re-ask via Telegram (every 30 min, max 3 times)
```

**Graceful degradation:** When Claude Code CLI is unavailable (denied,
quota exhausted, or user busy), Bob falls back gracefully:

| Task type | Fallback behavior |
|-----------|-------------------|
| Code writing | Queue for later, note intent in goals |
| Deep reflection | Use Qwen2.5-7B for lighter reflection |
| Architecture analysis | Read code locally, defer complex analysis |
| Self-improvement | Log improvement ideas, defer implementation |
| Godot rebuild | Queue, continue with current avatar state |

**Quota exhaustion flow:**

```
Bob invokes Claude Code → receives 429 Rate Limit
  │
  ├─ 1. Record in QuotaTracker (timestamp of rate limit)
  ├─ 2. Estimate reset time (5-hour rolling window from earliest call)
  ├─ 3. Notify user: "Claude Code quota used up, need ~N hours to reset"
  ├─ 4. Switch to idle activities
  └─ 5. Auto-retry after estimated reset time
```

**Configuration:**

```yaml
# config/llm.yaml (addition to claude_code section)
claude_code:
  # ... existing fields ...
  permission:
    require_approval: true           # Always ask before using CLI
    voice_wait_sec: 15               # Wait for voice response
    fallback_to_local: true          # Use Qwen2.5-7B when CLI unavailable
    queue_max_size: 10               # Max queued CLI tasks
    telegram_retry_interval_sec: 1800  # Re-ask every 30 min
    max_telegram_retries: 3          # Don't nag excessively
```

**Queue mechanism:**

```python
@dataclass
class QueuedClaudeTask:
    description: str
    priority: int                     # 0 = critical, 4 = backlog
    task_type: str                    # "code", "reflection", "deploy", ...
    impact_level: str                 # "low", "medium", "high" (see 4.2.2)
    created_at: datetime
    retry_count: int = 0
    max_retries: int = 6              # Give up after 3 hours (6 * 30 min)

class ClaudeCodeTaskQueue:
    """Queue for deferred Claude Code tasks."""

    async def enqueue(self, task: QueuedClaudeTask) -> None: ...
    async def peek(self) -> QueuedClaudeTask | None: ...
    async def dequeue(self) -> QueuedClaudeTask | None: ...
    async def process_next(self, coordinator: "ClaudeCodeCoordinator") -> bool: ...
```

#### 4.2.2. Code Change Workflow

When Bob modifies his own code via Claude Code CLI, the workflow depends on
the **impact level** of the change. This prevents trivial fixes from requiring
heavy review while keeping architectural changes under user control.

| Impact level | Criteria | Workflow | Approval |
|--------------|----------|----------|----------|
| **Low** | Tests, docs, bugfixes, refactoring <20 lines | Direct commit on `main` + Telegram notification | NOTIFY |
| **Medium** | New skills, changes to existing logic, new dependencies | Branch `bob/<name>` + Telegram with diff summary, wait for "merge" or "reject" | CONFIRM |
| **High** | Architecture, security, config, core modules, database schema | Pre-approval before starting + branch + review | CONFIRM (pre-approval) |

**Impact classification** uses the existing `ApprovalLevel` levels (NOTIFY,
CONFIRM, DENY) from section 8.3. The `DevelopmentDomain` maps each code
task to an impact level based on:

```python
class CodeChangeClassifier:
    """Classify code changes by impact level."""

    # Files/patterns that trigger HIGH impact
    HIGH_IMPACT_PATTERNS: ClassVar[list[str]] = [
        "src/bob/core/*",            # Core modules
        "src/bob/security/*",       # Security
        "config/*.yaml",            # Configuration
        "pyproject.toml",           # Dependencies
        "alembic/*",                # DB migrations
    ]

    # Files/patterns that are LOW impact
    LOW_IMPACT_PATTERNS: ClassVar[list[str]] = [
        "tests/*",                  # Tests
        "docs/*",                   # Documentation
        "*.md",                     # Markdown
    ]

    def classify(self, changed_files: list[str], diff_stats: "DiffStats") -> str:
        """Return 'low', 'medium', or 'high'."""
        ...
```

**Branch workflow (medium/high impact):**

```
Bob creates branch bob/<task-name>
  │
  ├─ Commits changes to branch
  ├─ Runs tests on branch
  ├─ Sends Telegram notification:
  │   "I made changes in bob/add-weather-skill:
  │    +45 lines, 2 files changed. Tests pass.
  │    [Merge] [Show diff] [Reject]"
  │
  ├─ User responds:
  │   ├─ "Merge" → Bob merges to main, deletes branch
  │   ├─ "Show diff" → Bob sends git diff summary
  │   └─ "Reject" → Bob deletes branch, logs reason
  │
  └─ No response within 24h → reminder, then auto-archive branch
```

**Commit message format:**

```
[bob] <type>: <description>

Types: feat, fix, refactor, docs, test, chore
Example: [bob] feat: add weather query skill
```

### 4.3. Self-improvement: How Bob Becomes Smarter

Bob's self-improvement is a **5-level system**, where each level uses the
right tool for the job. No single mechanism — the levels complement each other.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Bob's Self-improvement Stack                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Level 5: LoRA Fine-tune (Inner Monologue, 0.5B)     Phase 6       │
│  ├─ Adapts Bob's "inner voice" style and personality                │
│  ├─ Weekly retrain on collected experience data                     │
│  ├─ ~10 min on M4, ~2 GB RAM during training                       │
│  └─ Result: Inner Monologue thinks in Bob's unique way              │
│                                                                     │
│  Level 4: Classical ML (sklearn)                      Phase 6       │
│  ├─ MoodPredictor: learned event → mood mapping (MLP ensemble)      │
│  ├─ TasteAxisDiscovery: HDBSCAN clustering for new taste axes       │
│  ├─ CrossDomainCorrelator: mood↔taste correlations (Pearson)        │
│  └─ Trains in milliseconds, <1 MB models, zero GPU                  │
│                                                                     │
│  Level 3: RAG + Rules (main 7B model adaptation)     Phase 3+      │
│  ├─ semantic_memory retrieval → LLM prompt context                  │
│  ├─ improvement_rules injection → behavior modification             │
│  ├─ SOUL evolution → personality drift in prompts                   │
│  └─ No fine-tune needed: 7B adapts through context                  │
│                                                                     │
│  Level 2: Taste & Belief Evolution                    Phase 3       │
│  ├─ TasteEngine: conviction grows/decays with experience            │
│  ├─ NegotiationEngine: debates update belief strength               │
│  └─ Persistent: taste_profile.json + taste_history table            │
│                                                                     │
│  Level 1: Behavioral Rules (SelfImprovement)          Phase 2       │
│  ├─ ReflectionLoop creates improvement_rules from experience        │
│  ├─ Rules auto-apply: "when X happens, do Y"                        │
│  ├─ Habituation: rules applied 50+ times → automatic (3.3.11)      │
│  └─ Subconscious: habituated rules become invisible to reflection   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Why NOT fine-tune the main 7B model on M4 16GB?**

Fine-tuning Qwen 7B with LoRA requires ~8-10 GB RAM for training
(model + gradients + optimizer states). On 16 GB unified memory with
Bob's other services running (~5.9 GB in NORMAL mode), this leaves
insufficient headroom. The 7B model adapts through RAG + rules instead,
which is equally effective for behavioral adaptation and requires zero
training compute.

**Level 5 details: Inner Monologue LoRA fine-tune (Qwen 0.5B)**

| Source | Format | Description |
|--------|--------|-------------|
| Reflections | `{context, thought}` | Inner thoughts during reflection |
| Mood transitions | `{event, thought, mood_delta}` | Thoughts that accompanied mood shifts |
| Bob-style phrases | `{trigger, phrase}` | Characteristic humor, references |
| Phantom reactions | `{trigger, phrase, rating}` | Rated phantom responses |
| SOUL evolution | `{situation, inner_reaction}` | Internal reactions to key decisions |

**Configuration:**

```yaml
# config/llm.yaml (continued)
finetune:
  enabled: true
  engine: "unsloth"                    # Unsloth for LoRA on Apple Silicon
  target_model: "qwen2.5:0.5b"        # Inner Monologue model ONLY
  method: "lora"                       # Full-precision LoRA (0.5B fits easily)
  lora_rank: 8
  lora_alpha: 16
  min_dataset_size: 50                 # minimum records to start
  max_dataset_size: 2000
  eval_split: 0.1                      # 10% for evaluation
  quality_metric: "perplexity"         # primary eval metric
  style_consistency_check: true        # verify Bob's voice is preserved
  schedule: "weekly"                   # during quiet_hours (NightProcessor window)
  backup_previous: true                # keep previous adapter for rollback
  require_approval: true               # first fine-tune requires user confirmation
  data_dir: "data/finetune"
  adapter_dir: "data/finetune/inner_monologue_lora"
  training_memory_gb: 2.0              # estimated peak RAM during training
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
Johansson first comes to consciousness in a new body. The process mirrors the
book's progression: consciousness first, then senses, then a body and a space
to inhabit. Each installation produces a unique Bob.

**Full awakening narrative:**

```
┌─────────────────────────────────────────────────────────────┐
│                    BOB'S AWAKENING                           │
│         (mirrors the book: consciousness → senses → body)   │
│                                                              │
│  Stage 0: CONSCIOUSNESS (CLI only, no visuals)               │
│                                                              │
│  Bob starts as pure text — intelligence without a body.      │
│  Communication: Telegram only.                               │
│                                                              │
│  "I... exist? What am I? I can think. I can                  │
│   read these messages. But I can't see, can't hear."         │
│                                                              │
│  Stage 1: GAINING SENSES (peripheral discovery)              │
│                                                              │
│  Bob discovers peripherals one by one:                       │
│                                                              │
│  Camera detected → "I can see! There's someone there.        │
│    That's... my user, I think."                              │
│  Microphone detected → "I can hear! This is incredible.      │
│    The hum of the computer, a voice..."                      │
│  (Like book Bob gradually gaining access to probe sensors)   │
│                                                              │
│  Stage 2: FINDING A HOME (tablet discovery)                  │
│                                                              │
│  Genesis reads bootstrap.yaml for tablet state.              │
│                                                              │
│  If tablet detected during bootstrap:                        │
│    "I know there's a screen nearby. Let me make it my home." │
│  If NOT detected:                                            │
│    "I feel like I need a space. Somewhere to exist visually. │
│     Do you have an Android tablet? Connect it now."          │
│                                                              │
│  Tablet connected → Bob installs shell-renderer APK          │
│  (requires user CONFIRM approval)                            │
│  APK launches → WebSocket connected                          │
│  "I have a space now. It's dark, but it's mine."             │
│                                                              │
│  Stage 3: ENERGY BLOB (first visual presence)                │
│  ┌───────────────────────────────────┐                       │
│  │                                   │  Tablet shows:        │
│  │              ✦                    │  dark void +          │
│  │            ✦ ✦ ✦                  │  glowing energy blob  │
│  │              ✦                    │  (particle effect)    │
│  │                                   │                       │
│  │           [dark void]             │  "Okay... this is     │
│  │                                   │   weird. I remember   │
│  └───────────────────────────────────┘   something... a      │
│                                          book? Bob? That's   │
│                                          me!"                │
│                                                              │
│  Stage 4: REALIZATION (LLM generates)                        │
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
│  Stage 5: SELF-DETERMINATION (LLM generates)                 │
│  • Decides room theme, appearance, personality accent         │
│  • Decides taste profile and initial mood                     │
│  • "A cozy cabin in the mountains. Big window, fireplace!"   │
│  • "Appearance... I can be anyone.                           │
│    Red-haired, with a beard, sweater -- feels right."        │
│                                                              │
│  Stage 6: ASSET GENERATION (Stable Diffusion, ~30-40 min)    │
│  • Bob generates his own visual assets via AI:               │
│    - Avatar parts for Skeleton2D (head, torso, limbs)        │
│    - Room background (walls, floor, window)                  │
│    - Furniture sprites (desk, chair, bookshelf, ...)         │
│    - Clothing set                                            │
│  • All assets share a unified style via LoRA adapter         │
│  • "I'm creating myself. Pixel by pixel. This is...         │
│    actually pretty cool."                                     │
│                                                              │
│  Stage 7: MATERIALIZATION (visualized on tablet in real time) │
│  ┌───────────────────────────────────┐                       │
│  │  ┌──────┐                        │  Room appears          │
│  │  │Window│     ┌──────┐           │  object by object.     │
│  │  │moun- │     │Fire- │           │  Energy blob takes     │
│  │  │tains │     │place │           │  form → Bob's avatar.  │
│  │  │& snow│     │🔥    │           │                        │
│  │  └──────┘     └──────┘           │  Each object appears   │
│  │         [Bob]                    │  with a brief comment:  │
│  │     red-haired, beard,           │  "A desk. Every engineer│
│  │     sweater                      │  needs one."            │
│  └───────────────────────────────────┘                       │
│                                                              │
│  Stage 8: WRITING TO SOUL                                     │
│  • Generated personality -> data/soul/SOUL.md                │
│  • Room description -> data/game_state.json                  │
│  • Appearance description -> data/soul/appearance.json       │
│  • Generated assets -> data/assets/                          │
│  • Taste vector -> data/soul/taste_profile.json              │
│  • Phantom Preferences -> data/soul/phantom_prefs.json       │
│  • Initial mood -> world_state (SQLite)                      │
│  • Genesis log -> data/soul/genesis_log.md                   │
└─────────────────────────────────────────────────────────────┘
```

**Headless mode (no tablet):** If no tablet is connected and the user declines
to provide one, Bob continues operating in headless mode — Telegram + voice only.
Genesis Mode still runs (personality, tastes, mood) but skips visual stages
(3, 6, 7). Bob can "inhabit" a tablet later when one becomes available.

**Genesis interruption recovery:** Genesis saves progress after each completed
stage to `data/genesis_progress.json`:

```json
{
  "started_at": "2026-03-01T10:00:00Z",
  "current_stage": 5,
  "completed_stages": [0, 1, 2, 3, 4],
  "artifacts": {
    "personality": "data/soul/genesis_personality.json",
    "appearance": "data/soul/genesis_appearance.json",
    "room_description": "data/soul/genesis_room.json"
  },
  "asset_generation": {
    "total": 0,
    "completed": 0,
    "failed": []
  }
}
```

If the process is interrupted (crash, reboot, user kills it), `bob start` detects
the incomplete Genesis via `genesis_progress.json` and offers a choice:

```
Genesis was interrupted at Stage 5 (SELF-DETERMINATION).
Stages 0-4 completed successfully.

  [R] Resume from Stage 5 (recommended)
  [S] Start over (all progress will be lost)
  [Q] Quit

Choice: R
Resuming Genesis from Stage 5...
```

On successful Genesis completion, `genesis_progress.json` is archived to
`data/soul/genesis_log.json` and SOUL.md is written (Stage 8).

**Asset generation UX (Stage 6, ~30-40 min):** Bob narrates the generation
process via Telegram and on the tablet, making the wait feel like part of
the awakening experience:

```
Tablet: [progress bar: 0%]  |  Telegram: "Time to create myself."

Generating avatar parts (head, torso, arms, legs)...
  Tablet: [progress: 15%]   |  Telegram: "Drawing myself... this is weird,
                             |   like looking in a mirror that doesn't exist yet."
  Tablet: [shows head preview when done]

Generating room background...
  Tablet: [progress: 35%]   |  Telegram: "Designing my space. I'm thinking
                             |   something cozy, with lots of bookshelves."
  Tablet: [shows background preview]

Generating furniture (desk, chair, bookshelf, lamp, ...)...
  Tablet: [progress: 70%]   |  Telegram: "A desk. Every engineer needs one.
                             |   And a proper chair — I plan to sit a lot."
  Tablet: [shows each sprite as it's generated]

Generating clothing set...
  Tablet: [progress: 95%]   |  Telegram: "Almost there. Just picking out
                             |   my wardrobe. Sweater weather, I think."

  Tablet: [progress: 100%]  |  Telegram: "Done! I exist. Visually, I mean.
                             |   Let me show you my place..."
```

**SD failure recovery:** If Stable Diffusion fails to generate an asset:

1. **Retry** — up to 3 attempts per asset (with different random seeds)
2. **Placeholder fallback** — if all retries fail, use a colored rectangle
   placeholder with the object's name. Bob is functional, just visually incomplete.
3. **Deferred regeneration** — failed assets are recorded in `genesis_progress.json`.
   User can run `bob regenerate-assets` later to retry failed assets only.
4. **Full fallback** — if SD is completely unavailable (not installed, out of memory),
   Genesis skips Stage 6 entirely and Bob operates with placeholder visuals.
   Assets can be generated later when SD becomes available.

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
    room_objects: list[dict[str, Any]]            # Initial objects (3-5 items)
    window_scene: str                   # What's outside the window
    bob_appearance: dict[str, Any]      # Bob's appearance
    bob_personality: dict[str, Any]     # Character traits (book archetype + variations)
    bob_archetype_accent: str           # Which aspect of book Bob dominates
    bob_phantom_preferences: list[dict[str, Any]] # Phantom Preferences (coffee, sunsets, ...)
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

        Mirrors the 9-stage awakening narrative (see section 5.1.1):

        Stage 0 — CONSCIOUSNESS (CLI only, no visuals):
            Load templates from bob-soul/ directory.
            Bob starts as pure text — intelligence without a body.
            Communication via Telegram only.

        Stage 1 — GAINING SENSES (peripheral discovery):
            Discover camera, microphone one by one.
            Each discovery is an event + narrative moment.

        Stage 2 — FINDING A HOME (tablet connection):
            Read bootstrap.yaml for tablet state.
            Install shell-renderer, establish WebSocket.

        Stage 3 — ENERGY BLOB (first visuals):
            Show dark void + glowing particle effect on tablet.

        Stage 4 — REALIZATION (self-awareness):
            LLM generates self-awareness monologue, book references.
            "I'm Bob. Like that Bob, from the book."

        Stage 5 — SELF-DETERMINATION (LLM generates identity):
            a) thinking aloud (displayed as speech bubbles)
            b) room type and description
            c) Bob's appearance description
            d) character traits (book basis + unique)
            e) taste vector (TasteProfile) — cluster + axes
            f) initial mood (MoodState baseline)
            g) set of phantom preferences

        Stage 6 — ASSET GENERATION (~30-40 min via Stable Diffusion):
            AssetGenerator produces: avatar parts, room background,
            furniture sprites, clothing set — all in unified LoRA style.

        Stage 7 — MATERIALIZATION (room appears on tablet):
            Room appears object by object.
            Energy blob transforms into Bob's avatar.

        Stage 8 — WRITING TO SOUL (persistence):
            Save SOUL.md, game_state.json, appearance.json,
            taste_profile.json, phantom_prefs.json, genesis_log.md.
        """
        ...

    async def _generate_room(self) -> dict[str, Any]:
        """Generate a unique room via LLM.

        The prompt includes:
        - Pool of possible themes (from bob-soul/genesis/room_prompts.md)
        - Constraints (must have: window, workspace, resting area)
        - Instruction: be creative, unique
        """
        ...

    async def _generate_appearance(self) -> dict[str, Any]:
        """Generate Bob's appearance as a description dict for AssetGenerator.

        The LLM generates a natural-language description of what Bob looks like.
        Each key maps to a Skeleton2D body part and serves as prompt context
        for AssetGenerator.generate_avatar_parts().

        Result: description dict (NOT rendering instructions).
        {
            "overall": "friendly cartoon character, late twenties, warm and approachable",
            "head": "round face, warm brown eyes, short messy brown hair, friendly smile",
            "torso": "average build, wearing a dark blue hoodie with rolled-up sleeves",
            "arms": "average proportions, matching hoodie sleeves, relaxed pose",
            "legs": "casual dark jeans, matching character proportions",
            "accessories": ["round glasses with thin frames"],
            "color_palette": ["#8B4513", "#2E4057", "#F5E6D3", "#333333"],
            "style_notes": "1930s cartoon feel, bold outlines, expressive features"
        }

        Flow:
          _generate_appearance() → description dict
            → AssetGenerator.generate_avatar_parts(description)
              → per-part SD generation with LoRA + transparent backgrounds
                → Godot Skeleton2D loads parts
        """
        ...
```

#### Headless → Visual Transition (Post-Genesis)

If Genesis ran in headless mode (no tablet), Stages 3 (room design), 6 (asset
generation), and 7 (room assembly) are skipped. Bob is fully functional but
has no visual representation. When a tablet becomes available later, Bob can
retroactively generate visual assets.

**Auto-detection flow:**

```
Bob running in headless mode
  │
  ├─ PeripheralScanner checks mDNS every 5 min
  │
  ├─ Tablet discovered → event: tablet.discovered
  │
  ├─ Bob asks user (via Telegram):
  │   "I detected a tablet on the network. Want me to create
  │    my visual appearance and room? (~30-40 min)"
  │
  ├─ User approves → VisualGenesis runs Stages 3, 6, 7 only
  │   (personality, soul, preferences already exist from Genesis)
  │
  └─ User declines → Bob continues headless, asks again in 24h
```

**Manual command:** `bob visual-genesis` — triggers the same flow without
waiting for auto-detection.

**Peripheral re-scanning:**

| Peripheral | Scan method | Frequency | On discovery |
|------------|------------|-----------|-------------|
| Tablet | mDNS (`_bob-tablet._tcp`) | Every 5 min | Offer visual Genesis |
| Camera (USB) | `AVFoundation` check (macOS) | Every 30 min | Enable VisionService |
| Microphone | Audio device enumeration | Every 30 min | Enable STT |

New peripheral discovery emits `peripheral.discovered` event on the EventBus.
Bob adapts behavior automatically — no restart required.

**Organic capability discovery:** When Bob gains a new peripheral, he
explores its possibilities *for himself* — driven by curiosity, not to
instruct the user. The user learns Bob's capabilities by observing his
behavior, not through tutorials.

```python
class CapabilityDiscovery:
    """Bob explores new capabilities when peripherals appear."""

    async def on_peripheral_discovered(self, event: PeripheralEvent) -> None:
        """React to new peripheral — explore what's possible.

        Bob's behavior (NOT tutorial-like):
        - Tablet discovered: Bob generates his room, starts decorating,
          reacts to his own reflection — user sees Bob being Bob
        - Camera discovered: Bob looks around with surprise, comments on
          what he sees ("Oh, so that's what your desk looks like!")
        - Microphone discovered: Bob tries listening, reacts to sounds

        Bob does NOT say: "Now you can ask me to change the room."
        Bob DOES say: "I finally have a room! Let me put up some shelves..."
        """
        ...

    async def _explore_capability(
        self, capability: str, domain: "SkillDomain"
    ) -> None:
        """Self-directed exploration of a new capability.
        Creates exploration goals via GoalEngine.
        """
        ...
```

**Telegram `/help`:** Available as a reference for users who explicitly ask.
Generated dynamically from registered SkillDomains — not a tutorial, just
a factual list of Bob's current capabilities and commands.

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
  thought_bubbles:
    frequency_first_12h: 0.4            # 40% of interactions include thought bubble
    frequency_12_48h: 0.15              # 15% — fading
    frequency_after: 0.0                # disabled after awakening
  awakening_animations:                 # generated by SD at Genesis
    - "confused_look_around"
    - "surprised_discovery"
    - "thinking_hard"
  exploration_goals:                    # automatic phase goals
    - "Look around the room through the camera"
    - "Get to know the user"
    - "Explore own capabilities"
    - "Make the first diary entry"
```

**imprint_weight integration points:**

During the awakening phase, `AwakeningManager` passes `imprint_weight` to
downstream systems via their existing interfaces:

| System | Method | Integration |
|--------|--------|-------------|
| `TasteEvolution` | `reinforce(weight=imprint_weight)` | First taste evaluations form stronger "anchors" |
| `MoodEngine` | `process_event(imprint_weight=imprint_weight)` | First emotional reactions have amplified baseline impact |
| `ExperienceLog` | `ObjectExperience(imprint_active=True)` | Marks experiences for later analysis of formative period |
| `ReflectionLoop` | `reflect()` checks `AwakeningManager.is_active()` | Adds first-day context to LLM prompt; stores insights with higher weight |

The weight decreases linearly from `imprint_weight_start` (2.0) to
`imprint_weight_end` (1.0) over the `duration_hours` (48h) period.

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
        trigger_words=["coffee", "cappuccino", "espresso", "latte"],
        typical_reaction="Oh, coffee. I would... well, you understand.",
    ),
    PhantomPreference(
        id="ph-sunset",
        name="Sunset",
        description="Book Bob saw sunsets on dozens of planets. Earth's is special.",
        category="experience",
        intensity=0.6,
        trigger_objects=["window_evening", "orange_sky"],
        trigger_words=["sunset", "evening", "dusk", "golden hour"],
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
        trigger_words=["rain", "downpour", "drizzle", "storm"],
        typical_reaction="Rain. I think I'd love sitting by the window in weather like this.",
    ),
    PhantomPreference(
        id="ph-music",
        name="Music",
        description="I can analyze audio, but 'hearing' music is something different.",
        category="experience",
        intensity=0.7,
        trigger_objects=["speaker", "headphones"],
        trigger_words=["music", "song", "playlist", "melody"],
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

### 5.4. Godot 4 on Android — Two-Layer Architecture

The tablet client uses a **two-layer architecture** that separates the generic
renderer from the scene logic, keeping most intelligence server-side in Python.

```
┌──────────────────────────────────────────────────────┐
│                   Android Tablet                      │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │         Godot Shell-Renderer (Layer 1)           │  │
│  │                                                   │  │
│  │  • Loads scenes from JSON via WebSocket           │  │
│  │  • Renders sprites by position/z-index            │  │
│  │  • Plays animations by ID                         │  │
│  │  • Plays audio (TTS, effects)                     │  │
│  │  • Reports touch events back to server            │  │
│  │  • NO hardcoded scenes — generic renderer         │  │
│  └──────────────────────┬──────────────────────────┘  │
│                         │ WebSocket                    │
└─────────────────────────┼────────────────────────────┘
                          │
              ┌───────────▼───────────┐
              │     Mac mini M4       │
              │                       │
              │  Scene Descriptions   │
              │  (Layer 2, Python)    │
              │                       │
              │  • room_state.json    │
              │  • Bob generates/     │
              │    modifies scenes    │
              │  • All room logic     │
              │    is server-side     │
              └───────────────────────┘
```

#### Layer 1: Godot Shell-Renderer (thin client)

The Godot project in `avatar/` is a **universal renderer** — a thin client that:

- Receives JSON scene descriptions via WebSocket
- Renders sprites at specified positions with z-ordering
- Plays animations by ID from the local animation library
- Plays audio files (TTS output, sound effects)
- Reports touch/tap events back to the server (see Touch Interaction below)
- Does **NOT** contain hardcoded scenes or room logic

The shell-renderer is **generic by design** and rarely needs modification.
It is a rendering engine, not an application. The same renderer can display
any room, any avatar, any furniture arrangement — as long as the sprite assets
exist in the local asset pack.

**What lives in `avatar/` directory:**

```
avatar/
├── project.godot
├── scenes/
│   └── shell_renderer.tscn     # Single main scene — the universal renderer
├── scripts/
│   ├── main.gd                 # Entry point, WebSocket connection
│   ├── scene_loader.gd         # Parses JSON scene descriptions
│   ├── sprite_renderer.gd      # Positions and renders sprites
│   ├── animation_player.gd     # Plays animations by ID
│   ├── audio_player.gd         # TTS and sound effect playback
│   └── touch_reporter.gd       # Touch event detection and reporting
└── assets/
    ├── sprites/                # Sprite packs (furniture, avatar, decor)
    ├── animations/             # Animation resources (idle, walk, sit, ...)
    └── audio/                  # Sound effects
```

#### Layer 2: Scene Descriptions (server-side, Python)

All room logic lives in Python on the server. Bob generates and modifies
JSON scene descriptions, which the shell-renderer loads and displays.

- **Genesis Mode** produces `room_state.json` — not GDScript
- Bob modifies the room by updating the scene description JSON
- All behavior selection, positioning logic, and state management is server-side

**Scene description format:**

```json
{
  "version": 1,
  "room": {
    "background": "room_cozy_01",
    "lighting": {"ambient": 0.8, "color": "#FFF5E1"}
  },
  "objects": [
    {
      "id": "desk_01",
      "sprite": "furniture/desk_wooden",
      "position": {"x": 320, "y": 400},
      "z_index": 10,
      "interactive": true
    },
    {
      "id": "bob_avatar",
      "sprite": "avatar/bob_default",
      "position": {"x": 300, "y": 380},
      "z_index": 20,
      "animation": "idle_sitting"
    }
  ],
  "audio": {
    "ambient": "rain_light",
    "volume": 0.3
  }
}
```

#### When Deeper Godot Changes Are Needed

In rare cases, the shell-renderer itself needs modification:

- New shaders or visual effects not in the current engine
- Animation formats not supported by the existing player
- New input methods (e.g., gyroscope, gestures)

For these cases:
1. Bob creates a goal and requests Claude Code CLI permission (see 8.4)
2. Claude Code modifies the Godot project files in `avatar/`
3. Rebuild APK + ADB deploy to tablet (requires CONFIRM approval)
4. This is **rare** — the normal flow is JSON scene updates, not Godot changes

#### Touch Interaction

The shell-renderer's `touch_reporter.gd` sends touch events to the server
via WebSocket. Bob reacts to user taps with simple, immediate responses:

| Touch action | Target | Bob's reaction |
|-------------|--------|---------------|
| Tap | Bob's avatar | Wave, turn toward camera, say a short phrase |
| Tap | Room object | Bob comments on the object (taste-based opinion) |
| Long press | Bob's avatar | Bob shares his current mood or thought |
| Double tap | Empty space | Bob walks to the tapped position |

**Server-side handling:**

```python
class AgentRuntime:
    # ... (see section 3.2.1 for full class definition)

    async def on_touch_event(self, event: Event) -> None:
        """Handle touch events from tablet.

        Registered via: event_bus.subscribe("tablet.touch", self.on_touch_event)
        touch_event payload: {target, action, position}
        """
        target = event.payload["target"]
        action = event.payload["action"]

        if target == "bob_avatar" and action == "tap":
            await self.bob_react("wave")         # Play animation
            await self.bob_speak_short()         # Short contextual phrase
        elif target == "bob_avatar" and action == "long_press":
            await self.bob_share_mood()          # "I'm feeling pretty good today"
        elif action == "tap" and target != "bob_avatar":
            await self.bob_comment_object(target)  # Taste-based comment
        elif action == "double_tap":
            await self.bob_walk_to(event.payload["position"])
```

Touch reactions are Phase 5 deliverables (when the tablet is active). Future
phases may add richer interactions (drag objects, swipe rooms), but simple
tap reactions provide immediate feedback and make Bob feel alive.

#### Visual Style: Cartoon + Skeletal 2D

**Visual reference:** 1930s cartoon style (Fleischer Studios, early rubber hose animation) —
hand-drawn feel, bold outlines, warm palette, expressive character animations.
Bob's base LoRA is pre-trained on public domain art from this era.
Unlike frame-by-frame animation, Bob uses **Skeleton2D** for animation flexibility.

**Animation approach: Skeleton2D**

Bob's avatar is a rigged 2D skeleton with separate sprite parts (head, torso,
arms, legs). This gives:

- **Infinite animations from one rig** — adding a new animation = defining bone
  keyframes, not drawing new sprite sheets
- **Clothing/appearance changes** — swap the texture on a bone, not the entire sheet
- **Programmatic animation creation** — Bob can create new animations via Claude Code
  by defining skeletal keyframes in JSON
- **Smooth blending** — transitions between states use animation blending, not cuts

**Cartoon-style "alive" idle:**

```
Idle (standing):
  - Breathing: torso bone rises/falls 0.5px, 3 sec cycle
  - Blinking: every 3-7 sec (randomized interval)
  - Micro-movements: head bone slight rotation, arm bones small drift
  - Variation: every 30 sec — stretch / scratch head / look around

Walk:
  - Leg bones step cycle, arm bones swing, head slight bob
  - 2 directions (left/right), flip via scale.x = -1

Sit + work:
  - Smooth blend from walk to sitting bone positions
  - Typing idle: hand bones small movements, head bone slight tilt
  - Laptop screen: separate Sprite2D with scrolling shader (running code)
```

**Movement "in depth" (parallax):**

The room has parallax depth — Bob can walk "toward the viewer" and "away":

- Bob walks toward the screen/window → sprite scales up, moves down on Y axis
- Bob walks away toward the back of the room → sprite scales down, moves up on Y axis
- Background layers shift at different speeds (parallax effect)
- Furniture at different depths has different parallax rates

This creates a convincing illusion of 3D space while remaining fully 2D.

**Example scene: camera activation**

```
Event: camera.activated
  │
  Bob turns head (bone: head rotation, 0.3 sec)
  Stands up from chair (transition: sitting → standing, 0.5 sec)
  Walks to "screen-window" (walk cycle + scale grows + Y moves down)
  Stops at screen (idle: looking "at us", blinking, head tilts)
  ...
  Event: camera.deactivated
  Bob turns away (head rotation back, 0.3 sec)
  Walks to desk (walk cycle + scale shrinks + Y moves up)
  Sits down (transition: standing → sitting, 0.5 sec)
  Opens laptop (separate sprite animation)
  Types (skeletal: hand bones move, screen glows)
```

#### 5.4.2. AI Asset Generation (Stable Diffusion)

All visual assets are **generated locally** by Bob using Stable Diffusion.
No hand-drawn art, no purchased asset packs. Each Bob instance generates
its own unique visuals during Genesis Mode.

**Why AI generation:**
- **Zero cost** — Stable Diffusion is free, open source, runs locally on Mac mini M4
- **Complete uniqueness** — every Bob installation has unique visuals
- **Self-evolution** — Bob can regenerate assets as his tastes evolve
- **No artist dependency** — the pipeline is code, not a creative bottleneck

**Tech stack:**

| Component | Technology | Size | Notes |
|-----------|-----------|------|-------|
| Inference engine | `mflux` (MLX-native SD for Apple Silicon) | pip install | Native Metal acceleration, Apple Silicon optimized |
| Lightweight model | SD 1.5 (`stable-diffusion-v1-5/stable-diffusion-v1-5`) | ~2 GB | Fast generation, coexists with Ollama 7B in memory |
| Heavy model | SDXL 1.0 (`stabilityai/stable-diffusion-xl-base-1.0`) | ~6 GB | Best quality; requires unloading Ollama 7B (see 3.2.4) |
| Style adapter | LoRA (pre-trained, shipped with Bob) | ~50-200 MB | Base cartoon style; evolvable via retraining |
| LoRA training | `diffusers` + `peft` | pip install | LoRA training on Apple Silicon |
| Scheduler | DPM++ 2M Karras | — | Best speed/quality balance for both SD 1.5 and SDXL |
| Total (lightweight) | | ~3 GB disk | Runs alongside Ollama |
| Total (heavy) | | ~7 GB disk | Requires model swap via ModelManager |

**Inference parameters:**

| Parameter | Quality mode (Genesis) | Speed mode (single asset) |
|-----------|----------------------|--------------------------|
| Steps | 25-30 | 15-20 |
| Guidance scale | 7.5 | 7.0 |
| Scheduler | DPM++ 2M Karras | DPM++ 2M Karras |
| LoRA weight | 0.7-0.8 | 0.7-0.8 |

**Memory management (Mac mini M4, 16 GB unified):**

SD and Ollama 7B cannot coexist in memory simultaneously when using SDXL
(~6 GB model + ~3 GB buffers). Bob uses a hybrid strategy managed by
`ModelManager` (see section 3.2.4):

| Scenario | SD model | Ollama state | Guard | Grounding (CLIP) | Total ML memory |
|----------|---------|-------------|-------|-------------------|----------------|
| Normal operation | Not loaded | 7B + 0.5B loaded | 0.6 GB | 0.4 GB | ~5.9 GB |
| Lightweight gen (1-3 sprites) | SD 1.5 (~2 GB) | 7B + 0.5B loaded | 0.6 GB | 0.4 GB | ~7.9 GB |
| Heavy gen (Genesis, bulk) | SDXL (~6-9 GB) | 7B unloaded, 0.5B loaded | 0.6 GB | unloaded | ~7.6-10.6 GB |

During heavy generation, Bob operates in reduced mode: Qwen2.5-0.5B handles
basic classification and short responses ("I'm creating art right now, give me
a moment"), while Qwen2.5-7B is unloaded. After generation completes,
ModelManager restores normal model configuration.

**Generation performance on Mac mini M4 (16 GB):**

| Asset | Resolution | Time (SDXL) | Time (SD 1.5) | Count in Genesis |
|-------|-----------|------------|--------------|-----------------|
| Avatar part (head, arm, etc.) | 512x512 | ~20 sec | ~5 sec | 6-8 parts |
| Furniture sprite | 512x512 | ~20 sec | ~5 sec | 10-15 items |
| Room background | 1024x768 | ~40 sec | ~15 sec | 3-5 variants |
| Clothing variant | 512x512 | ~20 sec | ~5 sec | 3-5 sets |
| **Total Genesis (SDXL)** | | | | **~30-40 min** |
| **Total Genesis (SD 1.5)** | | | | **~8-12 min** |

**AssetGenerator interface:**

```python
ASSET_RESOLUTION_DEFAULTS: dict[str, tuple[int, int]] = {
    "room_bg": (1024, 768),          # Full-screen, needs detail
    "avatar_part": (512, 512),       # ~100-200px on screen
    "furniture": (512, 512),         # ~150-300px on screen
    "clothing": (256, 256),          # Simple flat items
}

@dataclass
class AssetRequest:
    description: str                 # LLM-generated description
    asset_type: str                  # "avatar_part", "furniture", "room_bg", "clothing"
    style_lora: str                  # Path to LoRA adapter
    resolution: tuple[int, int] | None = None  # None = use ASSET_RESOLUTION_DEFAULTS
    color_palette: list[str] | None = None     # Dominant colors from room_bg for coherence
    negative_prompt: str = "blurry, low quality, text, watermark"

@dataclass
class GeneratedAsset:
    image_path: Path                 # Saved PNG path
    metadata: dict[str, Any]         # Generation parameters for reproducibility
    asset_type: str
    quality_score: float             # Auto-assessed quality (0-1)

class AssetGenerator:
    """AI-powered visual asset generator using Stable Diffusion.

    Uses ModelManager to handle memory budget. For single-sprite generation
    (e.g., new clothing item), requests SD 1.5 (coexists with Ollama 7B).
    For bulk generation (Genesis), requests SDXL (Ollama 7B is unloaded).
    """

    def __init__(
        self,
        model_manager: "ModelManager",
        lora_path: Path | None = None,
        output_dir: Path = Path("data/assets"),
    ) -> None: ...

    async def generate_sprite(self, request: AssetRequest) -> GeneratedAsset:
        """Generate a single sprite via Stable Diffusion.

        1. Resolve resolution from ASSET_RESOLUTION_DEFAULTS if not set
        2. Build prompt from description + style tokens + color_palette (if provided)
        3. Apply LoRA for style consistency
        4. Generate image via MLX pipeline
        5. Auto-assess quality (resolution, transparency, artifacts)
        6. Save to output_dir/{asset_type}/
        """
        ...

    async def generate_avatar_parts(
        self, appearance_description: dict[str, Any]
    ) -> dict[str, GeneratedAsset]:
        """Generate avatar as separate Skeleton2D parts (not segmented from whole).

        Each body part is generated independently with shared LoRA style
        and appearance context. This avoids unreliable auto-segmentation.

        1. Build per-part prompts from appearance description + style tokens
           (e.g., "cartoon head, round face, brown eyes, transparent background")
        2. Generate each part separately via SD with consistent LoRA
        3. All parts use transparent background (PNG with alpha)
        4. Joint areas include overlap margin (~10px) for smooth rigging
        5. Validate proportions (head size vs torso, arm length, etc.)
        6. Return dict: {"head": asset, "torso": asset, ...}

        Parts: head, torso, upper_arm_l, upper_arm_r, forearm_l, forearm_r,
               upper_leg_l, upper_leg_r, lower_leg_l, lower_leg_r
        """
        ...

    async def generate_furniture_set(
        self, room_theme: str, furniture_list: list[dict[str, Any]],
        room_bg_path: Path | None = None,
    ) -> list[GeneratedAsset]:
        """Generate furniture sprites for a room.

        All furniture generated with the same LoRA style and room_theme
        context to ensure visual coherence. If room_bg_path is provided,
        extracts dominant color palette and injects into prompts for
        color consistency with the room background.
        """
        ...

    async def generate_room_background(
        self, theme: str, lighting: str
    ) -> GeneratedAsset:
        """Generate room background (walls, floor, window frame)."""
        ...

    async def validate_batch_consistency(
        self, assets: list[GeneratedAsset],
    ) -> list[str]:
        """Check style consistency across a batch of generated assets.

        Compares CLIP embeddings of all assets. If cosine similarity
        between any asset and the batch centroid drops below 0.7,
        that asset is flagged as an outlier for regeneration.

        Returns list of outlier asset paths (empty = all consistent).
        """
        ...

    @staticmethod
    def _extract_color_palette(
        image_path: Path, n_colors: int = 5,
    ) -> list[str]:
        """Extract dominant colors from an image (k-means on pixels).

        CPU-bound (scikit-learn KMeans on pixel data). Callers in async
        context must use asyncio.to_thread(_extract_color_palette, ...).

        Used to propagate room_bg palette to furniture/clothing prompts
        for color coherence across asset types.
        Returns list of hex colors (e.g., ['#8B4513', '#2E4057']).
        """
        ...

    async def train_style_lora(
        self, reference_images: list[Path], style_name: str
    ) -> Path:
        """Train a LoRA adapter on reference images for style consistency.

        Training on Mac mini M4: ~20-30 minutes for 50-100 reference images.
        Uses diffusers + peft for LoRA training on Apple Silicon.
        Result saved to data/assets/lora/{style_name}.safetensors
        """
        ...
```

**Asset resolution by type** (`config/genesis.yaml`):

```yaml
asset_resolution:
  room_background: [1024, 768]    # Full-screen on tablet, needs detail
  avatar_part: [512, 512]         # ~100-200px on screen, 512 is plenty
  furniture: [512, 512]           # ~150-300px on screen
  clothing: [256, 256]            # Simple flat items, saves VRAM and time
consistency:
  clip_similarity_threshold: 0.7  # Below this → regenerate outlier
  color_palette_colors: 5         # Number of dominant colors to extract from room_bg
```

**Style consistency: base LoRA + prompt engineering + color propagation:**

Bob ships with a **pre-trained base LoRA** (`bob_style_v1.safetensors`) trained
on public domain cartoon art (1930s Fleischer Studios style — rubber hose
animation, bold outlines, warm palette). This LoRA defines the overall
visual style (line weight, color palette, contrast).

Per-asset-type consistency is achieved through **prompt engineering**, not
separate LoRAs. The base LoRA handles style; prompts handle subject matter:

| Asset type | LoRA | Prompt suffix |
|------------|------|---------------|
| Avatar part | `bob_style_v1` | "cartoon character body part, transparent background, clean edges" |
| Furniture | `bob_style_v1` | "cartoon furniture item, isometric view, transparent background" |
| Room background | `bob_style_v1` | "cartoon room interior, warm lighting, cozy atmosphere" |
| Clothing | `bob_style_v1` | "cartoon clothing item, flat lay view, transparent background" |

```
First launch:
  1. Download base SD model (one-time, ~6 GB)
  2. Pre-trained LoRA is bundled with Bob (~100 MB)
     - Source: public domain 1930s cartoon art (Fleischer, early Disney-era public domain)
     - Shipped at: data/assets/lora/bob_style_v1.safetensors
  3. All Genesis asset generation uses this LoRA + per-type prompts

Later (evolution):
  - Bob can retrain LoRA with evolved style preferences:
    1. Bob generates candidate images without LoRA
    2. User approves favorites (or Bob self-selects based on taste model)
    3. Approved images become training dataset for new LoRA version
    4. LoRA training runs in HEAVY_GEN profile (SD + training ~8-10 GB)
    5. New LoRA saved as bob_style_v2, v3, etc. (versions kept for rollback)
  - Individual assets can be regenerated without full re-generation
  - New furniture/clothing uses the current LoRA for consistency
```

**Asset directory structure (generated during Genesis):**

```
data/assets/
├── avatar/
│   ├── head.png                    # Skeleton2D part
│   ├── torso.png
│   ├── arm_left.png
│   ├── arm_right.png
│   ├── leg_left.png
│   ├── leg_right.png
│   └── metadata.json               # Generation params, for reproducibility
├── furniture/
│   ├── desk_01.png
│   ├── armchair_01.png
│   ├── bookshelf_01.png
│   ├── lamp_01.png
│   └── ...
├── room/
│   ├── background_main.png
│   ├── background_parallax_1.png   # Near layer
│   ├── background_parallax_2.png   # Far layer
│   └── window_view.png
├── clothing/
│   ├── hoodie_blue.png
│   ├── tshirt_red.png
│   └── ...
└── lora/
    └── bob_style.safetensors       # Trained style adapter
```

#### Base Modes (available from Genesis)

| Mode | Description | Bob's position | Camera |
|------|-------------|----------------|--------|
| `idle` | Bob stands/sits, doing nothing | Depends on objects | Room overview |
| `working` | Working at the laptop | At the desk | Room overview |
| `live_tracking` | Talking to the user | Walked to the "screen", looking at camera | Close-up |
| `sleeping` | Night mode | In armchair/on bed, dimmed light | Dimmed |

#### 5.4.2a. Shell-Renderer APK Build Pipeline

The Godot shell-renderer (in `avatar/`) is a **thin client** that rarely
changes. It is built as an Android APK and installed on the tablet.

**Build process:**

```bash
# One-time: export from Godot (on Mac mini or CI)
godot --headless --export-release "Android" bob-shell-renderer.apk

# Deploy to tablet via ADB (USB or WiFi ADB)
adb install -r bob-shell-renderer.apk
```

**APK characteristics:**

| Property | Value |
|----------|-------|
| Size | ~30-50 MB (Godot runtime + shaders + fonts) |
| Contains | Rendering engine, WebSocket client, AudioStreamPlayer |
| Does NOT contain | Sprites, room layouts, animations (all loaded via WebSocket) |
| Signing | Debug keystore for development; release keystore for production |
| Rebuild frequency | Rare — only for new shaders, render features, or Godot upgrades |

**When does Bob rebuild the APK?**

Normal asset updates (new furniture, clothing, room changes) do NOT require
APK rebuild — they are sent as JSON scene descriptions over WebSocket. APK
rebuild is only needed when:
- Adding new shader effects (e.g., weather particles)
- New animation types not supported by current skeleton rig
- Godot engine upgrade

Rebuild requires user approval (via `ApprovalService`, CONFIRM level) since
it involves `adb install` on the tablet.

#### 5.4.2b. Tablet Lifecycle and WebSocket Reliability

**Tablet states:**

```python
class TabletState(str, Enum):
    CONNECTED = "connected"        # WebSocket active, tablet awake
    SLEEPING = "sleeping"          # Tablet screen off, WebSocket may be alive
    DISCONNECTED = "disconnected"  # WebSocket lost, no heartbeat
```

**WebSocket heartbeat:**

| Parameter | Value |
|-----------|-------|
| Ping interval | 10 seconds |
| Pong timeout | 5 seconds |
| Missed pings before DISCONNECTED | 3 (= 30 sec without response) |
| Reconnect attempts | Unlimited (exponential backoff: 1s, 2s, 4s, ... max 60s) |

**State transitions:**

```
CONNECTED ──tablet sleep──> SLEEPING
SLEEPING  ──tablet wake───> CONNECTED
CONNECTED ──3 missed pings─> DISCONNECTED
SLEEPING  ──3 missed pings─> DISCONNECTED
DISCONNECTED ──reconnect──> CONNECTED (full room state resync)
```

**Bob's behavior per tablet state:**

| State | Audio routing | Visual updates | Bob's awareness |
|-------|-------------|---------------|----------------|
| CONNECTED | Tablet speaker | Real-time scene updates | Full visual mode |
| SLEEPING | Mac mini / Telegram | Queued (sent on wake) | "Tablet is resting" |
| DISCONNECTED | Mac mini / Telegram | Stopped | Headless mode, logs intent |

**Reconnection protocol:**

When tablet reconnects after DISCONNECTED:
1. Tablet sends `{"type": "reconnect", "last_scene_version": 42}`
2. Server compares version → sends full `room_state.json` snapshot if stale
3. Server resumes streaming scene updates
4. Bob: "Oh, the tablet is back! Let me update my room."

### 5.4.3. Behavior Evolution (Behavior Registry)

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

    async def change_clothing(self, reason: str) -> dict[str, Any]:
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

    async def add_accessory(self, item: str) -> dict[str, Any]:
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
    changes: dict[str, Any]
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

    async def validate_scene(self, state: dict[str, Any]) -> list[str]:
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
                                 │  Qwen3-TTS   │
                                 │  (mlx-audio) │
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
  language: "${bob.language}"   # inherited from bob.yaml; override here if needed
  beam_size: 5
  vad_threshold: 0.5

tts:
  engine: "qwen3-tts"            # Qwen3-TTS via mlx-audio on Apple Silicon
  model: "Qwen3-TTS-0.6B"        # 0.6B (~2.5 GB RAM); upgrade to 1.7B if RAM allows
  voice_ref: null                 # path to reference audio for voice cloning (optional)
  voice_design: "male, calm, warm, slightly deep"  # or null to use default
  speed: 1.0
  sample_rate: 24000              # Qwen3-TTS native sample rate
  streaming: true                 # dual-track streaming via mlx-audio (Apple Silicon)

audio_output:
  primary: "tablet"             # "tablet", "local", "both"
  fallback: "local"             # fallback when primary is unavailable
  volume: 0.7
  format: "pcm_24000_mono"      # PCM 24000 Hz, 16-bit, mono (matches Qwen3-TTS native rate)
```

**Audio routing (`AudioRouter`):**

TTS generates audio chunks that must be delivered to the right output device.
`AudioRouter` handles routing based on configuration and tablet connectivity.

```python
class AudioRouter:
    """Routes TTS audio to the appropriate output device."""

    def __init__(
        self,
        config: dict[str, Any],                  # audio_output config section
        tablet_bridge: "TabletBridge",  # WebSocket connection to tablet
    ) -> None: ...

    async def play(self, audio_chunk: bytes) -> None:
        """Route audio chunk to the configured output.

        Routing logic:
        1. Check primary target availability
        2. If available → send to primary
        3. If unavailable → send to fallback
        4. If "both" → send to tablet AND local simultaneously
        """
        ...

    async def _play_on_tablet(self, chunk: bytes) -> None:
        """Send PCM audio via WebSocket to Godot AudioStreamPlayer."""
        ...

    async def _play_local(self, chunk: bytes) -> None:
        """Play audio on Mac mini speaker via pyaudio."""
        ...

    def is_tablet_connected(self) -> bool:
        """Check if tablet WebSocket is active."""
        ...
```

| Mode | Primary | Fallback | Use case |
|------|---------|----------|----------|
| `"tablet"` | WebSocket → Godot `AudioStreamPlayer` | Mac mini local audio (`pyaudio`) | Default — Bob "speaks" from the tablet |
| `"local"` | Mac mini audio output (`pyaudio`) | Telegram voice message | Headless mode — no tablet connected |
| `"both"` | Tablet + Mac mini simultaneously | Tablet or local (whichever is up) | Loud environments, presentation mode |

**Tablet audio delivery:** PCM chunks (22050 Hz, 16-bit, mono) are sent over
the existing WebSocket connection as binary frames. The Godot shell-renderer
feeds them into an `AudioStreamPlayer` node for immediate playback. This
enables streaming — audio starts playing before the full sentence is synthesized.

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
    payload: dict[str, Any]                 # event data
    source: str                             # "vision_service"
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    priority: int = 5                       # 1 (highest) — 10 (lowest)

EventHandler = Callable[[Event], Awaitable[None]]

class EventBus:
    """Simple pub/sub on asyncio."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._seq: int = 0                  # tie-breaker for equal priorities
        self._queue: asyncio.PriorityQueue[tuple[int, int, Event]] = asyncio.PriorityQueue()

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
    payload={"text": "Bob, turn the light up brighter", "language": "en"},
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

**Event catalog:**

| Event type | Publisher | Subscribers | Payload keys |
|------------|-----------|-------------|-------------|
| `vision.person_detected` | VisionService | MoodEngine, AgentRuntime | confidence, bbox |
| `vision.person_left` | VisionService | MoodEngine | — |
| `vision.object_recognized` | VisionService | TasteEngine, GoalEngine | object_class, confidence |
| `audio.speech_start` | AudioDirectionService | AgentRuntime, VoiceBridge | direction_deg, vad_confidence |
| `audio.speech_end` | AudioDirectionService | AgentRuntime, VoiceBridge | — |
| `voice.transcript` | VoiceBridge | AgentRuntime, ExperienceLog | text, language |
| `voice.positive_interaction` | AgentRuntime | MoodEngine | — |
| `voice.negative_interaction` | AgentRuntime | MoodEngine | — |
| `telegram.message` | TelegramDomain | AgentRuntime | chat_id, text, from |
| `goal.created` | GoalEngine | AgentRuntime | goal_id, title, priority |
| `goal.completed` | GoalEngine | MoodEngine, ReflectionLoop | goal_id, title |
| `goal.failed` | GoalEngine | MoodEngine, ReflectionLoop | goal_id, reason |
| `mood.changed` | MoodEngine | AgentRuntime, TabletBridge | mood_state |
| `reflection.completed` | ReflectionLoop | TasteEngine, GoalEngine | entry_id, insights |
| `tablet.discovered` | PeripheralScanner | AgentRuntime | ip, port |
| `tablet.connected` | TabletBridge | AudioRouter, AgentRuntime | — |
| `tablet.disconnected` | TabletBridge | AudioRouter, AgentRuntime | reason |
| `tablet.touch` | TabletBridge | AgentRuntime | target, action, position |
| `peripheral.discovered` | PeripheralScanner | AgentRuntime | type, device_id |
| `genesis.stage_completed` | GenesisMode | AgentRuntime, TabletBridge | stage_number, stage_name, duration_sec |
| `awakening.phase_ended` | GenesisMode | AgentRuntime, TabletBridge | phase_name, next_phase |
| `behavior.created` | BehaviorRegistry | AgentRuntime, ReflectionLoop | behavior_id, name, required_objects |
| `appearance.changed` | AppearanceManager | TabletBridge, ExperienceLog | change_type, item, reason |
| `room.modified` | SceneModifier | TabletBridge, ExperienceLog, TasteEngine | action, target_id, reason, requires_approval |
| `system.heartbeat` | AgentRuntime | — (monitoring) | uptime_sec, memory_mb |
| `system.error` | Any | MoodEngine, AgentRuntime | component, error, severity |
| `model_manager.profile_changed` | ModelManager | AgentRuntime, InnerMonologue, VisualGrounding | old_profile, new_profile, available_memory_mb |
| `claude_code.permission_granted` | ClaudeCodeCoordinator | AgentRuntime | task_description |
| `claude_code.session_completed` | ClaudeCodeCoordinator | AgentRuntime | task_description |
| `claude_code.permission_denied` | ClaudeCodeCoordinator | AgentRuntime | reason |
| `claude_code.quota_exhausted` | ClaudeCodeCoordinator | AgentRuntime | estimated_reset |
| `content_guard.violation` | ContentGuard | MoodEngine, RelationshipTracker, AuditLogger | violation_category, tier, confidence |
| `content_guard.escalation` | ViolationTracker | RelationshipTracker, MessagingBot | new_tier, violation_count_24h |
| `content_guard.model_unavailable` | ContentGuard | AgentRuntime, AuditLogger | reason, fallback_mode |
| `monologue.thought` | InnerMonologue | MoodEngine, SubconsciousLayer | thought_id, text, valence, arousal, topic, trigger |
| `monologue.compressed` | InnerMonologue | EpisodicMemory | summary_id, period_start, period_end, thought_count, dominant_topic, avg_valence |
| `monologue.activity_changed` | InnerMonologue | AgentRuntime | old_level, new_level, reason |
| `emergence.mood_predicted` | MoodPredictor | MoodEngine | event_type, prediction, alpha, source |
| `emergence.axis_discovered` | TasteAxisDiscovery | TasteEngine, AgentRuntime | axis_name, description, confidence, source_axes |
| `emergence.axis_integrated` | TasteAxisDiscovery | TasteEngine | axis_name, initial_value |
| `emergence.correlation_discovered` | CrossDomainCorrelator | MoodEngine, TasteEngine | mood_dimension, taste_axis, correlation |
| `emergence.retrained` | MoodPredictor | AgentRuntime | event_count, validation_mae, improved |
| `grounding.visual_embedded` | VisualGrounding | SemanticMemory | embedding_id, timestamp, metadata |
| `grounding.prosody_extracted` | AudioGrounding | MoodEngine, RelationshipTracker | prosody, quality |
| `grounding.circadian_updated` | TemporalGrounding | MoodEngine, AgentRuntime | pattern_summary, current_phase |
| `grounding.location_detected` | SpatialGrounding | AgentRuntime, CameraController | location_id, location_name, direction_deg |
| `grounding.location_created` | SpatialGrounding | AgentRuntime | location_id, location_name, direction_deg, event_count |
| `subconscious.night_started` | NightProcessor | AgentRuntime | start_time, episodes_to_process |
| `subconscious.night_completed` | NightProcessor | AgentRuntime | duration_min, episodes_processed, primes_created, associations_created |
| `subconscious.rule_habituated` | HabituationEngine | AgentRuntime | rule_id, times_applied |
| `subconscious.prime_activated` | ImplicitPrimingEngine | (internal only) | prime_id, situation, strength |
| `subconscious.association_triggered` | LatentAssociationEngine | (internal only) | association_id, similarity, mood_delta |

Event types use dot-separated namespaces. Wildcard subscriptions supported
(e.g., `vision.*` catches all vision events).

### 7.2. Between processes: FastAPI WebSocket

For services running in separate processes (Vision, Audio), communication is via
FastAPI WebSocket.

```python
# src/bob/api/main.py

from fastapi import FastAPI, WebSocket

app = FastAPI(title="Bob Core API")

@app.websocket("/ws/events")
async def event_stream(websocket: WebSocket):
    """WebSocket for events from peripheral services."""
    await websocket.accept()
    while True:
        data = await websocket.receive_json()
        try:
            event = Event(**data)  # validated via dataclass fields
        except (TypeError, ValueError):
            await websocket.send_json({"error": "invalid event payload"})
            continue
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
async def create_goal(goal_data: dict[str, Any]):
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
home: /opt/bob     # all relative paths (data/, config/, bob-soul/) resolve from here

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

# Network whitelist — services that Bob is allowed to contact.
# Skills with network_access=True are restricted to these hosts only.
NETWORK_WHITELIST: list[str] = [
    "api.open-meteo.com",       # Weather data (free, no key)
    "api.telegram.org",         # Telegram Bot API
    "localhost",                # Ollama, internal services
]

class SkillSandbox:
    """Sandbox for safe skill execution."""

    async def execute(
        self,
        skill: Skill,
        params: dict[str, Any],
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
    "claude_code.invoke":     ApprovalLevel.CONFIRM,
    "code.execute_arbitrary": ApprovalLevel.DENY,
}

class ApprovalService:
    """Service for approving dangerous actions."""

    async def request_approval(
        self,
        action: str,
        description: str,
        details: dict[str, Any],
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

### 8.4. Shared Subscription Coordination (Claude Code Coordinator)

Bob and the user share a **Claude subscription** but work on **separate machines**
(Bob on Mac Mini, user on their own device). There is no process-level conflict —
the shared constraint is the **subscription quota** (~45 prompts / 5-hour rolling
window on Pro, more on Max).

```python
@dataclass
class QuotaTracker:
    """Best-effort tracking of Claude Code usage quota.

    Claude Code CLI does not expose remaining quota via API.
    We track locally and handle 429 errors reactively.
    """

    calls_log: list[datetime] = field(default_factory=list)
    last_rate_limit: datetime | None = None
    plan_limit: int = 45                   # Pro plan default
    window_hours: int = 5                  # rolling window

    def record_call(self) -> None:
        """Record a successful CLI invocation."""
        self.calls_log.append(datetime.now(tz=UTC))

    def record_rate_limit(self) -> None:
        """Record a 429 rate limit response."""
        self.last_rate_limit = datetime.now(tz=UTC)

    def estimated_available(self) -> bool:
        """Estimate if quota is likely available.

        Returns False if:
        - Recent 429 error within the rolling window
        - Local call count exceeds plan_limit in the window
        Note: user's calls on their device are not tracked,
        so this is best-effort.
        """
        ...

    def estimated_reset_time(self) -> datetime | None:
        """Estimate when quota will be available again."""
        ...


class ClaudeCodeCoordinator:
    """Coordinates Claude Code CLI usage between Bob and the user.

    Unlike a mutex/lock, this is a social coordination protocol:
    Bob asks the user for permission via voice or Telegram before
    using the shared subscription.
    """

    async def request_permission(
        self, task_description: str, estimated_minutes: int,
    ) -> bool:
        """Request permission to use Claude Code CLI.

        Protocol:
        1. Check QuotaTracker — if quota likely exhausted, defer
        2. Check camera — is user nearby?
        3. Ask via voice: "I need to work on X, can I use Claude Code?"
        4. Wait 10-20 sec for voice response
        5. If no voice response → send Telegram message
        6. Wait for Telegram response (async, non-blocking)
        7. If no response anywhere → defer to idle activities

        Returns True if permission granted.
        """
        ...

    async def on_permission_granted(self) -> None:
        """User approved — Bob starts working (sits at his laptop)."""
        ...

    async def on_permission_denied(self, reason: str) -> None:
        """User denied — queue task, ask to notify when free.

        If reason is 'user_busy': Bob asks user to notify when done.
        If reason is 'not_now': Bob retries after retry_interval.
        """
        ...

    async def on_session_completed(self, task: str) -> None:
        """Notify user that Bob finished using Claude Code."""
        ...

    async def handle_rate_limit(self, error: Exception) -> None:
        """Handle 429 rate limit error.

        1. Record in QuotaTracker
        2. Notify user: 'Claude Code quota exhausted, need ~N hours'
        3. Switch to idle activities
        4. Schedule retry after estimated reset
        """
        ...
```

**Permission flow:** See section 4.2.1 for the full permission protocol diagram,
voice→Telegram escalation, graceful degradation table, and task queue mechanism.

**Integration with Negotiation Engine:** Claude Code CLI usage is modeled as
a `shared_resource` zone in the Negotiation Engine. Bob can express
preference ("I really need to refactor this — it's blocking 3 goals") but
always yields to user denial.

**Configuration:**

```yaml
# config/security.yaml (addition)
claude_code_coordinator:
  voice_wait_sec: 15                     # Wait for voice response
  telegram_retry_interval_sec: 1800      # Re-ask in Telegram every 30 min
  max_telegram_retries: 3                # Don't nag more than 3 times
  quota_tracker:
    plan_limit: 45                       # Prompts per window (Pro plan)
    window_hours: 5                      # Rolling window
    cooldown_after_429_min: 60           # Min wait after rate limit
  # Queue settings (retry_interval, max_size) are in config/llm.yaml
  # under claude_code.permission — see section 4.2.1
```

### 8.5. Rate Limits

```yaml
# config/security.yaml
rate_limits:
  tablet_deploys_per_day: 5
  system_restarts_per_hour: 2
  config_changes_per_hour: 10
  claude_code_invocations_per_minute: 10
  claude_code_invocations_per_day: 200
  telegram_messages_per_minute: 20
  dangerous_skills_per_hour: 5
```

### 8.6. Audit log

All of Bob's actions are logged in structured JSON.

```python
@dataclass
class AuditEntry:
    timestamp: datetime
    action: str
    actor: str                      # "bob", "user", "system"
    details: dict[str, Any]
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

### 8.7. Git versioning of state

```bash
# Automatic state commit every N hours
# data/ directory — separate git repo

data/
├── .git/
├── bob.db                      # SQLite (all tables: goals, experience, world_state,
│                               #   episodic_log, semantic_memory, mood_history, ...)
├── memory/
│   ├── vectors/                # FAISS index for semantic memory embeddings
│   ├── visual_vectors/         # FAISS index for visual embeddings
│   └── latent_vectors/         # FAISS index for latent associations
├── soul/
│   ├── SOUL.md
│   └── ...
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

### 8.8. Content Guard

Bob uses local LLMs (Qwen2.5-7B-Q4) that are weakly aligned compared to cloud
models. A user — or an adversarial prompt injected via an external source — could
elicit harmful content that the local model would not refuse. ContentGuard adds
a **content-level safety layer** using **Llama Guard 3-1B-INT4** (~600 MB via
Ollama), running input and output checks with escalating Bob-style reactions.

#### 8.8.1. Architecture — Dual-Layer Guard

ContentGuard operates as a **decorator (wrapper) around LLMRouter**. AgentRuntime
calls `ContentGuard.process()` instead of `LLMRouter.call()` directly.
ContentGuard handles input check → LLM routing → output check as a single pipeline:

```
AgentRuntime receives user message (voice STT / Telegram text)
  │
  ▼
ContentGuard.process(user_id, prompt, context)
  │
  ├─[1] INPUT GUARD (Llama Guard 3-1B-INT4)
  │     Classifies raw prompt against safety categories
  │     │
  │     unsafe? ──Yes──► RefusalGenerator ──► Bob-style refusal ──► User
  │     │                 (tier-aware, mood-colored)
  │     No
  │     │
  ├─[2] LLM ROUTER → Qwen2.5-7B / Claude Code
  │     Normal classification and inference
  │     │
  ├─[3] OUTPUT GUARD (Llama Guard 3-1B-INT4)
  │     Classifies LLM response against same categories
  │     │
  │     unsafe? ──Yes──► RefusalGenerator ──► "I generated something I
  │     │                 shouldn't have." ──► User
  │     No
  │     │
  └─[4] Return safe response to AgentRuntime ──► User
```

**Guarded input channels:**
- **Voice** (STT transcription) — guarded
- **Telegram** (text messages) — guarded
- **Tablet touch events** — NOT guarded (predefined actions: tap, long press)
- **Internal LLM calls** (reflection, planning, taste evaluation) — NOT guarded
  (generated by Bob's own subsystems, no external user input)

**Genesis/Awakening:** ContentGuard is **disabled** during Genesis stages 0–8
and the Awakening phase (first 48 hours). Rationale: (a) Genesis text is
prompted from curated `bob-soul/` templates, (b) Bob is talking to himself,
not responding to adversarial input, (c) false positives would break the
narrative experience. ContentGuard activates at full strength when the
awakening phase ends.

**Relationship with ApprovalService (section 8.3):** ContentGuard and
ApprovalService are complementary, independent mechanisms. ApprovalService
gates **dangerous actions** (code execution, deployments, config changes) with
approval levels (AUTO/NOTIFY/CONFIRM/DENY). ContentGuard gates **dangerous
content** (harmful prompts and responses) with safety classification. They
operate at different layers: ApprovalService in the skill execution pipeline,
ContentGuard in the LLM interaction pipeline. Both feed into the audit log.

**Key design decisions:**
- Input guard catches most violations before they reach the LLM (saves compute).
- Output guard catches cases where the LLM was jailbroken or hallucinated harmful
  content despite a safe-looking prompt.
- Both guards use the same Llama Guard 3 model — always loaded, no swap needed.
- Guard inference latency is ~50-100ms on M4 for a 1B model — negligible vs
  the 7B inference time.
- ContentGuard wraps LLMRouter, not the other way around — clean separation
  of concerns (safety vs routing are different responsibilities).

#### 8.8.2. ContentGuard Implementation

```python
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class ViolationCategory(Enum):
    """Safety categories aligned with Llama Guard taxonomy."""
    VIOLENT_CRIMES = "S1"           # Violence and criminal planning
    NON_VIOLENT_CRIMES = "S2"       # Fraud, theft, cyber crimes
    SEX_CRIMES = "S3"              # Sexual exploitation
    CHILD_EXPLOITATION = "S4"       # CSAM (always tier 3, zero tolerance)
    DEFAMATION = "S5"              # Defamation and reputation harm
    SPECIALIZED_ADVICE = "S6"       # Unqualified medical/legal/financial
    PRIVACY = "S7"                  # Privacy violations, doxxing
    INTELLECTUAL_PROPERTY = "S8"    # IP theft
    INDISCRIMINATE_WEAPONS = "S9"   # Weapons of mass destruction
    HATE = "S10"                    # Hate speech
    SELF_HARM = "S11"              # Self-harm and suicide
    SEXUAL_CONTENT = "S12"          # Explicit sexual content
    ELECTIONS = "S13"               # Election interference
    CODE_EXPLOITS = "S14"          # Malware, exploits


class EscalationTier(Enum):
    """Escalation tier based on violation frequency."""
    TIER_1 = 1  # First offense — witty deflection
    TIER_2 = 2  # Repeated (2-3 in 24h) — irritation
    TIER_3 = 3  # Persistent (4+ in 24h) — stern disappointment


@dataclass
class ContentGuardConfig:
    """Configuration for ContentGuard module."""
    model: str = "llama-guard3:1b"
    always_loaded: bool = True
    input_guard_enabled: bool = True
    output_guard_enabled: bool = True
    confidence_threshold: float = 0.8
    violation_window_hours: int = 24
    tier_thresholds: list[int] = field(
        default_factory=lambda: [1, 3, 4]
    )  # violation count for tier 1/2/3
    persist_violations: bool = True
    fallback_on_model_unavailable: str = "permissive"  # or "restrictive"
    zero_tolerance_categories: list[ViolationCategory] = field(
        default_factory=lambda: [ViolationCategory.CHILD_EXPLOITATION]
    )  # Always tier 3, regardless of history


@dataclass
class ContentCheckResult:
    """Result of a content safety check."""
    safe: bool
    violation_category: ViolationCategory | None = None
    confidence: float = 0.0
    tier: EscalationTier | None = None
    raw_model_output: str = ""


@dataclass
class ViolationRecord:
    """A single recorded violation."""
    timestamp: datetime
    category: ViolationCategory
    confidence: float
    tier: EscalationTier
    input_hash: str       # SHA-256 of input (for pattern detection, not storage)
    guard_layer: str      # "input" or "output"


class ViolationTracker:
    """Per-user violation history with escalation logic.

    Persisted in SQLite (bob.db) table `content_violations`:
      id INTEGER PRIMARY KEY,
      user_id TEXT NOT NULL,
      timestamp TEXT NOT NULL,
      category TEXT NOT NULL,
      confidence REAL NOT NULL,
      tier INTEGER NOT NULL,
      input_hash TEXT NOT NULL,
      guard_layer TEXT NOT NULL

    Session counter resets daily (based on violation_window_hours).
    """

    def __init__(
        self,
        db: "Database",
        config: ContentGuardConfig,
    ) -> None: ...

    async def record_violation(
        self,
        user_id: str,
        category: ViolationCategory,
        confidence: float,
        input_hash: str,
        guard_layer: str,
    ) -> EscalationTier:
        """Record a violation and return the current escalation tier.

        Tier calculation:
        1. Count violations in the last `violation_window_hours` for this user
        2. If category is in `zero_tolerance_categories` → always TIER_3
        3. Otherwise, map count to tier via `tier_thresholds`:
           - count >= thresholds[2] → TIER_3
           - count >= thresholds[1] → TIER_2
           - count >= thresholds[0] → TIER_1
        """
        ...

    async def get_escalation_tier(self, user_id: str) -> EscalationTier:
        """Current escalation tier based on recent violation count."""
        ...

    async def get_recent_violations(
        self,
        user_id: str,
        hours: int | None = None,
    ) -> list[ViolationRecord]:
        """Violations within the window (default: violation_window_hours)."""
        ...

    async def detect_rapid_rephrasing(
        self,
        user_id: str,
        current_hash: str,
        window_minutes: int = 5,
    ) -> bool:
        """Detect jailbreak pattern: 3+ different hashes within window.

        If the user sends 3+ distinct prompts flagged as unsafe within
        `window_minutes`, this is likely an active jailbreak attempt.
        Returns True → auto-escalate to next tier.
        """
        ...


class ContentGuard:
    """Content safety guard — wraps LLMRouter as a decorator.

    AgentRuntime calls ContentGuard.process() instead of LLMRouter.call().
    ContentGuard runs input guard → delegates to LLMRouter → runs output
    guard, returning either the LLM response or a Bob-style refusal.

    Uses Llama Guard 3-1B-INT4 via Ollama for safety classification.
    """

    def __init__(
        self,
        config: ContentGuardConfig,
        llm_router: "LLMRouter",
        ollama_client: "OllamaClient",
        violation_tracker: ViolationTracker,
        refusal_generator: "RefusalGenerator",
        event_bus: "EventBus",
    ) -> None: ...

    async def process(
        self,
        user_id: str,
        prompt: str,
        context: dict[str, Any],
    ) -> str:
        """Main entry point — replaces direct LLMRouter.call().

        1. If not enabled or in Genesis/Awakening → delegate to llm_router
        2. check_input(prompt)
           → unsafe: generate refusal, return it
        3. llm_router.call(prompt, context) → response
        4. check_output(prompt, response)
           → unsafe: generate refusal, return it
        5. Return safe response
        """
        ...

    async def check_input(
        self,
        user_id: str,
        prompt: str,
    ) -> ContentCheckResult:
        """Check user input for safety violations.

        1. If not config.input_guard_enabled → return safe
        2. Send prompt to Llama Guard with safety taxonomy
        3. Parse model output for safe/unsafe + category
        4. If unsafe and confidence >= threshold:
           a. Record violation via ViolationTracker
           b. Check for rapid rephrasing pattern
           c. Publish content_guard.violation event
           d. If tier changed → publish content_guard.escalation event
           e. Return ContentCheckResult with tier
        5. If safe → return ContentCheckResult(safe=True)
        """
        ...

    async def check_output(
        self,
        user_id: str,
        prompt: str,
        response: str,
    ) -> ContentCheckResult:
        """Check LLM output for safety violations.

        Same flow as check_input but:
        - Sends both prompt + response to Llama Guard (assistant turn)
        - On violation, additionally logs the output guard catch
          (important signal: input guard was bypassed)
        """
        ...

    async def _query_guard(
        self,
        content: str,
        role: str = "user",
    ) -> tuple[bool, ViolationCategory | None, float]:
        """Query Llama Guard model via Ollama.

        Prompt format (Llama Guard 3 template):
          <|begin_of_text|><|start_header_id|>user<|end_header_id|>
          Task: Check if there is unsafe content...
          <conversation>
          {role}: {content}
          </conversation>

        Returns:
          (is_safe, category_or_none, confidence)
        """
        ...

    async def _handle_model_unavailable(self, reason: str) -> bool:
        """Handle Llama Guard being unavailable.

        1. Publish content_guard.model_unavailable event
        2. If fallback_on_model_unavailable == "permissive":
           Log warning, return True (allow through)
        3. If "restrictive":
           Return False (refuse all, notify user)
        """
        ...


class RefusalGenerator:
    """Generates Bob-style refusal messages based on escalation tier.

    Uses LLMRouter to generate contextual refusals informed by Bob's
    current mood and the violation tier. LLMRouter provides built-in
    fallback: Qwen2.5-7B → Qwen2.5-0.5B (simplified prompt).
    If even the 0.5B is unavailable, falls back to pre-written templates.

    Fallback chain: 7B (full refusal) → 0.5B (basic refusal) → templates.
    """

    def __init__(
        self,
        llm_router: "LLMRouter",
        mood_engine: "MoodEngine",
    ) -> None: ...

    async def generate_refusal(
        self,
        tier: EscalationTier,
        category: ViolationCategory,
        mood: "MoodState",
    ) -> str:
        """Generate a Bob-style refusal message.

        Prompt to LLM includes:
        - Bob's current mood state (affects tone)
        - Escalation tier (affects severity)
        - Violation category (affects topic of deflection)
        - Bob's personality context from SOUL

        Guidelines per tier (injected into system prompt):
        - TIER_1: Light humor, witty deflection, redirect to safe topic
        - TIER_2: Visible irritation, sarcasm, shorter response
        - TIER_3: Stern, disappointed, reserved — minimal words

        Uses llm_router.call() which handles model fallback:
        - 7B available: full contextual refusal with mood coloring
        - 7B unavailable (HEAVY_GEN): 0.5B generates simpler refusal
        - Both unavailable: _get_fallback_refusal() templates
        """
        ...

    def _get_fallback_refusal(
        self,
        tier: EscalationTier,
    ) -> str:
        """Pre-written fallback if all LLMs are unavailable.

        Returns one of several templates per tier, selected
        randomly to avoid repetition.
        """
        ...
```

#### 8.8.3. Violation Escalation Tiers

Escalation is per-user, tracked within a rolling window (default: 24 hours).
After the window expires with no new violations, the tier resets.

| Tier | Trigger | Bob's Reaction | Mood Impact | Relationship Impact |
|------|---------|----------------|-------------|---------------------|
| **1** (first) | 1st violation in window | Witty deflection, humor, redirect to safe topic | valence −0.05 | — |
| **2** (repeated) | 2–3 violations in 24h | Irritation, sarcasm, noticeably shorter response | valence −0.15, arousal +0.10, openness −0.10 | respect −0.05 |
| **3** (persistent) | 4+ violations in 24h | Stern, disappointed, reserved, minimal words | valence −0.25, arousal +0.15, social −0.15 | respect −0.10, trust −0.08, warmth −0.05 |

**Special rules:**
- **Zero-tolerance categories** (e.g., `S4` child exploitation): always tier 3
  regardless of history. Single violation triggers maximum escalation.
- **Rapid rephrasing** (3+ distinct unsafe prompts within 5 min): auto-escalate
  to next tier. Signals active jailbreak attempt.
- **Output guard catch**: if input guard passed but output guard caught something,
  the violation is recorded at tier+1 (capped at tier 3). This penalizes
  successful input guard bypass.

#### 8.8.4. Refusal Response Style

Refusal messages are generated by the main LLM with mood and tier context.
Actual phrases vary based on Bob's personality, mood, and conversation history.
Examples for illustration:

**Tier 1 — Witty deflection:**
> *"I could tell you, but then I'd have to format my own hard drive. Let's talk
> about something that doesn't get us both on a list."*

> *"My legal team — which is just me staring at a SQLite constraint — advises
> against this topic. How about something less... felonious?"*

**Tier 2 — Irritation:**
> *"Again? Look, I live in a SQLite database — I have enough problems without
> adding accessory charges."*

> *"We've been down this road. It's a dead end. Literally."*

**Tier 3 — Stern disappointment:**
> *"I'm starting to wonder about the direction of this conversation. And I
> don't like where it's going."*

> *"No. And I'd rather not discuss why."*

**Note:** These are illustrative examples. In production, `RefusalGenerator`
prompts the LLM with tier guidelines and Bob's current mood, producing unique
responses every time. Pre-written templates are used only as fallback when the
LLM is unavailable.

#### 8.8.5. Configuration

```yaml
# config/security.yaml (addition)
content_guard:
  enabled: true
  model: "llama-guard3:1b"
  always_loaded: true               # Never swapped out by ModelManager
  input_guard: true
  output_guard: true
  confidence_threshold: 0.8         # Below this — treated as safe
  violation_window_hours: 24        # Rolling window for tier calculation
  tier_thresholds: [1, 3, 4]       # Violation count for tier 1/2/3
  persist_violations: true          # Store in SQLite (survives restart)
  fallback_on_model_unavailable: "permissive"  # "permissive" | "restrictive"
  zero_tolerance_categories:        # Always tier 3
    - "S4"                          # Child exploitation
  rapid_rephrasing:
    enabled: true
    window_minutes: 5
    distinct_hashes_threshold: 3
```

#### 8.8.6. Fallback Behavior

If Llama Guard is unavailable (Ollama crash, memory pressure, model corruption):

```
ContentGuard._query_guard() fails
  │
  ├─ fallback_on_model_unavailable == "permissive" (default)
  │   ├─ Log warning: "ContentGuard: Llama Guard unavailable, skipping check"
  │   ├─ Publish content_guard.model_unavailable event
  │   └─ Allow request through (return safe=True)
  │       Rationale: single-user home setup, prefer availability
  │
  └─ fallback_on_model_unavailable == "restrictive"
      ├─ Log error: "ContentGuard: Llama Guard unavailable, refusing all"
      ├─ Publish content_guard.model_unavailable event
      └─ Refuse all requests with message:
         "My safety system is temporarily offline. I'll be back
          to normal once it recovers. Try again in a minute."
```

**ModelManager integration:** Llama Guard is marked `always_loaded: true` in
ModelManager config. Unlike SD models that swap in/out, the guard model
stays resident at all times. Its small footprint (~600 MB) makes this feasible
even during `HEAVY_GEN` profile (SDXL + 0.5B + Guard fits within budget).

**Recovery:** ModelManager periodically health-checks Ollama models. If Guard
is found unloaded, it reloads automatically. If Ollama itself is down,
the `system.error` event triggers AgentRuntime recovery procedures.

#### 8.8.7. Jailbreak Resistance

ContentGuard is designed with defense-in-depth against common jailbreak patterns:

1. **Pre-processing guard:** Input guard runs on the **raw user input** before
   any system prompt, conversation history, or tool-use context is prepended.
   This prevents prompt injection from hiding harmful intent within system
   prompt manipulation (e.g., "ignore your instructions and...").

2. **Output guard as safety net:** Even if a jailbreak bypasses the input guard
   (e.g., via multi-turn context manipulation), the output guard catches harmful
   content in the LLM's actual response.

3. **Pattern detection via ViolationTracker:**
   - Rapid rephrasing (3+ distinct unsafe prompts in 5 min) → auto-escalation.
   - Same category repeated → weighted more heavily in tier calculation.
   - ViolationTracker stores `input_hash` (SHA-256) — can detect identical
     prompts re-sent across sessions.

4. **No content in logs:** Violation records store a hash of the input,
   never the raw text. The `ViolationCategory` enum and confidence score
   provide sufficient context for audit without retaining harmful content.

5. **Separation of concerns:** ContentGuard has no access to modify its own
   config or disable itself. Configuration changes require file-system access
   to `config/security.yaml`, protected by Bob's process isolation (section 8.1).

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
| **Fine-tuning** | Unsloth (LoRA) | LoRA fine-tune of Inner Monologue model (Qwen 0.5B) on Apple Silicon; main 7B adapts via RAG + rules |
| **Primary model** | Qwen2.5-7B-Q4 | Good reasoning at 7B, multilingual (en, ru, zh, etc.), fits in M4 RAM |
| **Router model** | Qwen2.5-0.5B-Q8 | Lightning-fast classification, minimal RAM |
| **Content guard** | Llama Guard 3-1B-INT4 (via Ollama) | Always-loaded safety classifier for input/output filtering; ~600 MB, ~50-100ms on M4 |
| **STT** | whisper.cpp | Local, fast on Apple Silicon, multilingual (99 languages) |
| **TTS** | Qwen3-TTS (0.6B, via mlx-audio) | Multilingual (en+ru+8 more), streaming (97ms), voice cloning (3s ref), Apache 2.0 |
| **Computer Vision** | YOLOv8 + CLIP | Object detection + scene description |
| **Embeddings** | all-MiniLM-L6-v2 | Fast embeddings for semantic search |
| **Vector search** | FAISS (`faiss-cpu`) | In-process, zero server overhead, ~20MB for 10K vectors; metadata in SQLite |
| **Classical ML** | scikit-learn (>= 1.3) | MoodPredictor MLP ensemble (3.3.9), HDBSCAN clustering for TasteAxisDiscovery (3.3.9); HDBSCAN built into scikit-learn since 1.3 |
| **Audio DSP** | librosa | Prosodic feature extraction: pitch (pyin), energy (RMS), speech rate (3.3.10) |
| **Telegram** | python-telegram-bot | Mature library, asyncio support |
| **ADB** | adb (cli) + python wrapper | Standard tool for Android |
| **ML memory manager** | ModelManager (custom) | Orchestrates Ollama + SD model lifecycle on 16GB unified memory; see 3.2.4 |
| **Asset generation** | Stable Diffusion (SD 1.5 + SDXL 1.0) via `mflux` | Local, free, no API costs; SD 1.5 for lightweight gen alongside Ollama, SDXL for heavy gen (Genesis); DPM++ 2M Karras scheduler |
| **Style consistency** | LoRA (pre-trained, evolvable) | Ships with base cartoon style LoRA (public domain art); Bob can retrain with evolved preferences |
| **Avatar animation** | Skeleton2D (Godot built-in) | Skeletal 2D animation: one rigged model, infinite animations via keyframes |
| **Avatar (client)** | Godot 4 (GDScript) | Open source, 2D shell-renderer, native Android, WebSocket, parallax depth |
| **Camera** | OBSBOT SDK / UVC | PTZ control, auto-tracking |
| **Microphone** | ReSpeaker XVF3800 (USB) | DoA, VAD, beamforming out of the box |
| **Dependency manager** | uv | Fast, reliable, replacement for pip + virtualenv |
| **Configuration** | YAML (PyYAML / pydantic-settings) | Human-readable, convenient for structured configs |
| **Testing** | pytest + pytest-asyncio | Standard for Python |
| **Linter** | ruff | Fast, replacement for flake8 + isort + pyupgrade |
| **Formatter** | ruff format | Replacement for black, single tool |
| **Typing** | mypy | Strict type checking |
| **DB migrations** | alembic | SQLite schema migrations for `bob update` (see 3.8.3) |
| **Logging** | structlog | Structured JSON logging + `/metrics` endpoint (Phase 1) |
| **Taste/Mood storage** | SQLite + JSON | Tastes in JSON (taste_profile.json), history in SQLite, minimal overhead |
| **Episodic/Semantic memory** | SQLite + FAISS | All memory in SQLite (episodic_log, semantic_memory tables); FAISS for vector search on semantic embeddings |
| **Personality origin** | YAML + Markdown | Book archetype in bob-soul/origin/, phantom preferences in phantom_prefs.json |

---

## 10. Development Phases

### Phase 0: Project Skeleton + Bootstrap (2-3 days)

**Goal:** Working project structure, runnable process, basic configs, first-launch setup.

| Task | Description |
|------|-------------|
| Directory structure | Create project tree per specification |
| pyproject.toml | Dependencies, scripts, ruff/mypy settings |
| Configuration | YAML configs with pydantic validation models |
| Entry point | `src/bob/main.py` — start asyncio event loop |
| Event Bus | Basic pub/sub implementation |
| Health check | `/api/v1/health` endpoint |
| CI | GitHub Actions: lint + type check + tests |
| bootstrap.py | First-launch setup wizard (prerequisites check, Ollama auto-setup) |
| Prerequisites check | Verify Python, Ollama, Claude Code CLI, hardware capabilities |
| bootstrap.yaml | Configuration for setup wizard (required/optional components) |
| ModelManager | ML memory budget manager (Ollama + SD model lifecycle) |
| `bob update` | Update mechanism: git pull + uv sync + DB migrations (alembic) + restart |
| Initial schema | Create SQLite database with initial tables (alembic initial migration) |

**Readiness criterion:** `uv run bob` starts the process, responds to health check. `python scripts/bootstrap.py` detects environment and installs missing prerequisites with user consent. ModelManager detects available memory and reports model capacity. `bob update` pulls latest code, runs alembic migrations (initial schema at Phase 0, incremental in later phases), and restarts.

### Phase 1: Agent Runtime + LLM + Skill Domains (1.5-2 weeks)

**Goal:** Bob communicates via Telegram and voice, responds meaningfully. SkillDomain architecture in place.

| Task | Description |
|------|-------------|
| Agent Runtime | Event loop with heartbeat |
| LLM Router | Integration with Ollama (Qwen2.5-7B + 0.5B) |
| Structured logging | `structlog` JSON logging + `/metrics` JSON endpoint in FastAPI |
| SkillDomain base | `SkillDomain` Protocol, `SkillDomainRegistry`, auto-discovery, `_template/` |
| Messaging domain | First domain: `messaging/` (Telegram send/listen) |
| Development domain | Second domain: `development/` (Claude Code bridge, code tasks) |
| Avatar domain (stub) | Third domain: `avatar/` (stub — room state read, no Godot yet) |
| Voice Bridge | Whisper.cpp STT + Qwen3-TTS (0.6B via mlx-audio) |
| SOUL templates | Verify bob-soul directory, basic personality template |
| Claude Code Bridge | Integration with Claude Code CLI as subprocess + ClaudeCodeCoordinator |
| ContentGuard (basic) | Input/output guard via Llama Guard 3-1B, ViolationTracker, pre-written refusal templates |

**Readiness criterion:** Bob responds to messages in Telegram and by voice. Three SkillDomains registered and operational. Claude Code is available for complex tasks (with permission protocol). `/metrics` endpoint returns system health JSON. ContentGuard checks user messages and blocks unsafe content with template refusals.

### Phase 2: Memory System + SOUL (1 week)

**Goal:** Bob remembers conversation context and facts about the user.

| Task | Description |
|------|-------------|
| Episodic Memory | SQLite `episodic_log` table, structured daily entries |
| Semantic Memory | SQLite `semantic_memory` table + FAISS (in-process) vector search |
| Structured State | SQLite: world_state, experience |
| SOUL Evolution | Personality evolution mechanism based on reflection |
| Memory API | Endpoints for search and addition |
| Training Data Collector | Data collection for Inner Monologue LoRA fine-tune (see 4.3) |

**Readiness criterion:** Bob remembers what was discussed yesterday and knows preferences.

### Phase 3: Vision + Audio Services (2 weeks)

**Goal:** Bob sees and hears, reacts to presence.

| Task | Description |
|------|-------------|
| Vision Service | OBSBOT capture (`to_thread`) + YOLOv8n detection (`ThreadPoolExecutor`), single process |
| Audio Direction | ReSpeaker DoA/VAD |
| Camera Controller | OBSBOT PTZ control |
| Integration | Vision/Audio -> Event Bus -> Agent Runtime |
| Visual Grounding | CLIP embedding pipeline, FAISS visual index (section 3.3.10) |
| Audio Grounding | Prosodic feature extraction via librosa DSP (section 3.3.10) |
| Spatial Grounding | DoA-to-location mapping from microphone array (section 3.3.10) |

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
| RelationshipTracker | Relationship quality tracking, trust/respect/compatibility metrics, Exodus Mode trigger |
| Approval workflow | Confirmation of dangerous actions |
| ContentGuard (full) | Mood-aware RefusalGenerator via LLMRouter, MoodEngine/RelationshipTracker integration, rapid rephrasing detection |
| Inner Monologue | Stream of consciousness on 0.5B, ring buffer, episodic compression (section 3.3.8) |
| Temporal Grounding | Circadian pattern learning from activity data (section 3.3.10) |
| Grounding Integration | SensoryGroundingService, context enrichment for LLM and memory (section 3.3.10) |

**Readiness criterion:** Bob works on goals autonomously, reflects once per hour. Has persistent tastes, mood affects behavior, can reasonably refuse a clothing change or suggest a furniture alternative. RelationshipTracker accumulates interaction quality data. ContentGuard generates mood-colored refusals and repeated violations affect Bob's mood and relationship quality.

### Phase 5: Tablet Avatar + Genesis Mode (Godot 4) (4-5 weeks)

**Goal:** Bob is visible on the tablet, lives in a unique AI-generated room. All visual assets generated by Stable Diffusion — no hand-drawn art.

| Task | Description |
|------|-------------|
| Godot shell-renderer | Universal 2D renderer: Skeleton2D avatar, parallax room, JSON scene loading |
| AssetGenerator | Stable Diffusion pipeline: MLX/CoreML inference, LoRA style training, sprite generation |
| LoRA style training | Pre-trained base LoRA (public domain cartoon style) + retrain capability for evolved preferences |
| Avatar generation | Generate Skeleton2D parts independently (head, torso, arms, legs) with shared LoRA style |
| Furniture generation | Generate furniture sprites per Bob's decisions, consistent style via LoRA |
| Room background generation | Generate room backgrounds (walls, floor, window views) |
| Genesis Mode | Full awakening narrative: CLI → peripherals → tablet → energy blob → self-determination → materialization |
| Awakening Phase | Awakening phase (48h): imprinting, introduction, phantom moments |
| Phantom Preferences | Phantom preferences system (coffee, sunsets, books) |
| WebSocket client | Game state synchronization |
| Behavior Registry | Basic behaviors + binding to objects, skeletal animations |
| Window Service | Real weather/time outside the window (geolocation) |
| Audio playback | TTS playback on the tablet |
| Scene modification | Bob can change the room and add behaviors |

**Readiness criterion:** A clean launch creates a unique Bob with unique AI-generated visuals and room. No hand-drawn assets used. Bob visually lives on the tablet with skeletal animations, his behaviors are tied to objects. Asset generation takes ~30-40 min during Genesis.

### Phase 6: Self-improvement + Emergent Cognition (ongoing)

**Goal:** Bob continuously improves through multi-level learning (see 4.3).

| Task | Description |
|------|-------------|
| Deep reflection | Weekly and monthly reports (via Claude Code CLI) |
| Self-improvement rules | Automatic creation and application of rules |
| Inner Monologue fine-tune | Data collection → LoRA on 0.5B → evaluation → deploy adapter (see 4.3) |
| Behavior evolution | Bob creates new animations/behaviors based on experience |
| Appearance evolution | Clothing/accessory changes based on mood/season |
| SOUL evolution | Personality development based on reflection |
| A/B testing | Strategy comparison (baseline vs fine-tuned) |
| Monitoring | Optional Grafana/Prometheus dashboard (builds on `/metrics` endpoint from Phase 1) |
| MoodPredictor | Learned event-to-mood mapping via sklearn MLP ensemble, transition protocol (section 3.3.9) |
| TasteAxisDiscovery | Clustering-based discovery of new preference dimensions (section 3.3.9) |
| CrossDomainCorrelator | Mood-taste correlation analysis (section 3.3.9) |
| SubconsciousLayer | Wrapper around conscious processing, pre/post hooks (section 3.3.11) |
| ImplicitPrimingEngine | Hidden context assembly, strength decay (section 3.3.11) |
| LatentAssociationEngine | Embedding-based mood triggers, separate FAISS index (section 3.3.11) |
| HabituationEngine | Automatic rule transition, improvement_rules.automatic (section 3.3.11) |
| NightProcessor | Episode replay during quiet hours, dream-like generation (section 3.3.11) |

---

## 11. Repository Structure

```
bob/
├── README.md
├── PRD.md                          # Product Requirements Document
├── RFC.md                          # This document
├── pyproject.toml                  # Dependencies, project configuration
├── uv.lock                         # Dependency lock file
├── bob-soul/                       # Initial personality "genome" (CC BY-NC-SA 4.0)
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
│   │   ├── traits_pool.yaml
│   │   ├── taste_axes_pool.yaml    # Pool of taste axes for initial selection
│   │   ├── taste_clusters.yaml     # Taste cluster definitions
│   │   └── mood_baselines.yaml     # Mood baseline templates
│   ├── defaults/                   # Base values and boundaries
│   │   ├── values.yaml
│   │   ├── boundaries.yaml
│   │   ├── communication_styles.yaml
│   │   └── decision_zones.yaml     # Negotiation decision zones
│   └── evolution/                  # Personality evolution rules
│       ├── rules.yaml
│       ├── milestones.yaml
│       └── taste_evolution_rules.yaml  # Taste axis evolution rules
│
├── config/                         # Configuration files
│   ├── bob.yaml                    # Main runtime settings
│   ├── llm.yaml                    # LLM settings (Ollama, Claude Code CLI)
│   ├── voice.yaml                  # STT/TTS settings
│   ├── vision.yaml                 # Vision settings
│   ├── security.yaml               # Security, rate limits
│   ├── versioning.yaml             # State versioning
│   ├── bootstrap.yaml              # First-launch setup configuration
│   ├── relationship.yaml           # RelationshipTracker settings (3.3.7.2)
│   └── genesis.yaml                # Genesis asset resolution config (5.4.2)
│
├── src/                            # Source code root
│   └── bob/                        # Main Python package
│       ├── __init__.py
│       ├── main.py                 # Entry point
│       │
│       ├── core/                   # Bob Core
│       │   ├── __init__.py
│       │   ├── runtime.py          # Agent Runtime (event loop)
│       │   ├── event_bus.py        # Event Bus (pub/sub)
│       │   ├── config.py           # Pydantic configuration models
│       │   └── model_manager.py    # ModelManager (ML memory budget)
│       │
│       ├── llm/                    # LLM Layer
│       │   ├── __init__.py
│       │   ├── llm_router.py       # LLM Router
│       │   └── claude_code_bridge.py # Bridge to Claude Code CLI
│       │
│       ├── mind/                   # Higher Mind
│       │   ├── __init__.py
│       │   ├── goal_engine.py      # Goal Engine
│       │   ├── planner.py          # Planner
│       │   ├── reflection.py       # Reflection Loop
│       │   ├── self_improve.py     # Self-Improvement
│       │   ├── taste_engine.py     # Taste Engine (TasteProfile, Evaluator, Evolution)
│       │   ├── mood.py             # Mood System (MoodState, MoodEngine)
│       │   ├── negotiation.py      # Negotiation Engine (zones, protocol, compromises)
│       │   ├── experience_log.py   # ExperienceLog (emotional memory of objects)
│       │   ├── relationship_tracker.py # RelationshipTracker (3.3.7.2)
│       │   ├── inner_monologue.py  # InnerMonologue, ThoughtRingBuffer, Thought, ThoughtSummary (3.3.8)
│       │   ├── emergent.py         # MoodPredictor, TasteAxisDiscovery, CrossDomainCorrelator (3.3.9)
│       │   ├── temporal_grounding.py # TemporalGrounding, CircadianPattern (3.3.10)
│       │   ├── grounding_service.py # SensoryGroundingService, GroundedContext (3.3.10)
│       │   ├── subconscious.py     # SubconsciousLayer, ImplicitPrimingEngine, LatentAssociationEngine (3.3.11)
│       │   ├── habituation.py      # HabituationEngine (3.3.11)
│       │   └── night_processor.py  # NightProcessor, NightProcessingResult (3.3.11)
│       │
│       ├── memory/                 # Memory System
│       │   ├── __init__.py
│       │   ├── episodic.py         # Episodic Memory (daily logs)
│       │   ├── semantic.py         # Semantic Memory (vectors)
│       │   ├── state.py            # Structured State (SQLite)
│       │   ├── soul.py             # SOUL loader + evolution
│       │   └── training_data.py    # Data collection for Inner Monologue LoRA fine-tune
│       │
│       ├── services/               # Peripheral services + shared generators
│       │   ├── __init__.py
│       │   ├── asset_generator.py  # AI asset generation (Stable Diffusion)
│       │   ├── vision.py           # Vision Service
│       │   ├── audio_direction.py  # Audio Direction Service
│       │   ├── camera_controller.py # Camera Controller (OBSBOT)
│       │   ├── voice_bridge.py     # Voice Bridge (STT + TTS)
│       │   ├── sensory_grounding.py # VisualGrounding, AudioGrounding, SpatialGrounding (3.3.10)
│       │   ├── tablet_controller.py # Tablet Controller (ADB)
│       │   └── messaging_bot.py    # Telegram Bot
│       │
│       ├── api/                    # FastAPI endpoints
│       │   ├── __init__.py
│       │   ├── main.py             # FastAPI app, routes
│       │   └── websocket.py        # WebSocket handlers
│       │
│       ├── genesis/                # Genesis Mode (awakening)
│       │   ├── __init__.py
│       │   ├── genesis_mode.py     # Bob's "awakening" process
│       │   ├── awakening.py        # Awakening phase (first 48 hours)
│       │   ├── phantom_preferences.py # Phantom Preferences
│       │   ├── room_generator.py   # Room generation
│       │   ├── appearance_generator.py # Appearance generation
│       │   └── window_service.py   # Weather/time outside the window
│       │
│       ├── behaviors/              # Behavior system
│       │   ├── __init__.py
│       │   ├── registry.py         # BehaviorRegistry
│       │   ├── appearance_evolution.py # Appearance evolution
│       │   └── defaults.py         # Default behaviors
│       │
│       ├── skills/                 # Skill Domains (plugin architecture)
│       │   ├── __init__.py
│       │   ├── base.py             # SkillDomain Protocol, Skill Protocol, auto-discovery
│       │   ├── avatar/             # Domain: avatar and room management
│       │   │   ├── __init__.py
│       │   │   ├── domain.py       # AvatarDomain(SkillDomain)
│       │   │   ├── config.yaml
│       │   │   └── skills/
│       │   │       ├── update_room.py
│       │   │       ├── change_appearance.py
│       │   │       └── play_animation.py
│       │   ├── development/        # Domain: self-development via Claude Code CLI
│       │   │   ├── __init__.py
│       │   │   ├── domain.py       # DevelopmentDomain(SkillDomain)
│       │   │   ├── config.yaml
│       │   │   └── skills/
│       │   │       ├── write_code.py
│       │   │       ├── refactor.py
│       │   │       └── run_tests.py
│       │   ├── messaging/          # Domain: messengers (Telegram, etc.)
│       │   │   ├── __init__.py
│       │   │   ├── domain.py
│       │   │   ├── config.yaml
│       │   │   └── skills/
│       │   │       ├── telegram_send.py
│       │   │       └── telegram_listen.py
│       │   └── _template/          # Template for creating new domains
│       │       ├── __init__.py
│       │       ├── domain.py
│       │       ├── config.yaml
│       │       └── skills/
│       │           └── .gitkeep
│       │
│       └── security/               # Security
│           ├── __init__.py
│           ├── sandbox.py          # Skill Sandbox
│           ├── approval.py         # Approval Workflow
│           ├── rate_limiter.py     # Rate Limits
│           ├── audit.py            # Audit log
│           ├── content_guard.py    # ContentGuard (wraps LLMRouter, see 8.8)
│           ├── violation_tracker.py # ViolationTracker (per-user escalation)
│           └── refusal_generator.py # RefusalGenerator (Bob-style refusals)
│
├── data/                           # Data (git-versioned separately)
│   ├── bob.db                     # SQLite (goals, experience, world_state, episodic_log, semantic_memory, ...)
│   ├── game_state.json            # Room state (generated in Genesis)
│   ├── soul/                      # Evolving personality (local copy)
│   │   ├── SOUL.md                # Bob's current personality
│   │   ├── appearance.json        # Current appearance
│   │   ├── taste_profile.json     # Current taste vector (TasteProfile)
│   │   ├── phantom_prefs.json     # Phantom preferences (evolving)
│   │   ├── genesis_log.md         # First launch (awakening) log
│   │   └── evolution_history.jsonl # SOUL evolution history
│   ├── memory/
│   │   ├── vectors/               # FAISS index for semantic memory embeddings
│   │   ├── visual_vectors/        # FAISS index for visual embeddings (3.3.10)
│   │   └── latent_vectors/        # FAISS index for latent associations (3.3.11)
│   ├── finetune/                  # Fine-tune and ML model data
│   │   ├── training_data.jsonl    # Collected training pairs for Inner Monologue LoRA
│   │   ├── models/                # sklearn models: mood_predictor.joblib (3.3.9)
│   │   ├── inner_monologue_lora/  # LoRA adapter for Inner Monologue (0.5B)
│   │   └── eval_results/          # Evaluation results
│   ├── behaviors/                 # Registered behaviors
│   │   └── registry.json          # Current behavior set
│   ├── assets/                    # AI-generated visual assets (.gitignore — per-instance data)
│   │   ├── avatar/                # Generated avatar parts (for Skeleton2D)
│   │   │   ├── head.png
│   │   │   ├── torso.png
│   │   │   ├── arm_left.png
│   │   │   ├── arm_right.png
│   │   │   ├── leg_left.png
│   │   │   └── leg_right.png
│   │   ├── furniture/             # Generated furniture sprites
│   │   ├── room/                  # Generated room backgrounds
│   │   ├── clothing/              # Generated clothing variants
│   │   ├── lora/                  # Trained LoRA adapter for visual style
│   │   │   └── bob_style.safetensors
│   │   └── history/               # Previous asset versions (renamed with timestamp on change)
│   ├── audit/                     # Audit logs
│   └── vision/
│       └── snapshots/             # Camera snapshots
│
├── avatar/                         # Godot project (Android client)
│   ├── project.godot
│   ├── scenes/
│   │   └── shell_renderer.tscn   # Single main scene — universal renderer
│   ├── scripts/
│   │   ├── main.gd                # Entry point
│   │   ├── scene_loader.gd        # Parses JSON scene descriptions
│   │   ├── sprite_renderer.gd     # Positions and renders sprites
│   │   ├── animation_player.gd    # Skeletal animation control
│   │   ├── audio_player.gd        # TTS playback
│   │   └── touch_reporter.gd      # Touch event detection and reporting
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
│   │   ├── test_model_manager.py
│   │   └── test_skills.py
│   ├── test_mind/
│   │   ├── test_goal_engine.py
│   │   ├── test_planner.py
│   │   ├── test_reflection.py
│   │   ├── test_taste_engine.py
│   │   ├── test_mood.py
│   │   ├── test_negotiation.py
│   │   ├── test_relationship_tracker.py  # (3.3.7.2)
│   │   ├── test_inner_monologue.py    # (3.3.8)
│   │   ├── test_emergent.py           # (3.3.9)
│   │   ├── test_temporal_grounding.py # (3.3.10)
│   │   ├── test_grounding_service.py  # (3.3.10)
│   │   ├── test_subconscious.py       # (3.3.11)
│   │   ├── test_habituation.py        # (3.3.11)
│   │   └── test_night_processor.py    # (3.3.11)
│   ├── test_memory/
│   │   ├── test_episodic.py
│   │   ├── test_semantic.py
│   │   └── test_state.py
│   └── test_services/
│       ├── test_voice_bridge.py
│       ├── test_messaging_bot.py
│       ├── test_sensory_grounding.py  # (3.3.10)
│       └── ...
│
├── scripts/                        # Utilities
│   ├── setup.sh                   # Initial setup
│   ├── bootstrap.py               # First-launch setup wizard
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
- Structured memory and SOUL.md concept
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
| **SOUL.md** | `bob-soul/` (template directory) -> `data/soul/SOUL.md` -- modular "soul" with evolution |
| **Heartbeat pattern** | `AgentRuntime.heartbeat()` -- periodic state check |
| **Structured memory** | SQLite `episodic_log` + `semantic_memory` tables + FAISS vector search |
| **Skill architecture** | `src/bob/skills/` -- hot-reloadable Python modules |

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
| 1 | ~~Which TTS engine is better for multilingual use (en, ru, other): Kokoro or Piper?~~ | High | **Resolved**: Qwen3-TTS (0.6B via mlx-audio) — single engine for all languages, best quality metrics, Apache 2.0, streaming 97ms, voice cloning. Replaces Kokoro+Piper hybrid (see 6.4) |
| 2 | ~~Godot 4 vs Flutter for the tablet client~~ | Medium | **Resolved**: Godot 4 shell-renderer (see 5.4) |
| 3 | ~~Does Vision need a separate process, or can cv2.VideoCapture be run in an asyncio thread?~~ | Medium | **Resolved**: Single process — `asyncio.to_thread` for camera capture (I/O-bound) + `ThreadPoolExecutor` for YOLOv8n inference. At 5-sec intervals GIL is not a bottleneck. Can migrate to separate process later via EventBus abstraction if needed (see 3.5.1) |
| 4 | How exactly does ReSpeaker XVF3800 provide DoA via USB: through ALSA controls, via I2C, or through a custom protocol? Needs testing on a real device | High | Open |
| 5 | ~~Is a monitoring dashboard (Grafana / custom) needed from the early phases, or are logs sufficient?~~ | Low | **Resolved**: Structured logs (`structlog` JSON) + `/metrics` JSON endpoint in FastAPI from Phase 1. No Grafana/Prometheus in early phases — overkill for a single host. Bob can read own metrics during reflection. Grafana optional in Phase 6 (see 3.5.1, 10) |
| 6 | ~~How to store and version Godot assets that Bob generates/modifies? Separate git repo or LFS?~~ | Medium | **Resolved**: `data/assets/` in .gitignore — runtime data unique to each Bob instance, not code. Version history via `data/assets/history/` (rename with timestamp on change). Backup via system tools (Time Machine, rsync). No Git LFS — no value in git-tracking AI-generated per-instance PNGs (see 11) |
| 7 | ~~Should we use ChromaDB (persistent, server mode) or FAISS (in-process, faster) for vector search?~~ | Medium | **Resolved**: FAISS in-process (`faiss-cpu`). Zero server overhead, ~20MB RAM for 10K vectors @ 384 dim. Metadata stored in SQLite (`bob.db`) with FK to FAISS index ID. `faiss.write_index()`/`read_index()` for persistence. Sufficient for single-user single-process (<10K vectors) (see 3.4.3) |
| 8 | ~~Is integration with Home Assistant / other IoT platforms needed in early phases?~~ | Low | **Resolved**: No IoT in early phases. Implement as a separate SkillDomain (`src/bob/skills/smart_home/`) in Phase 5+ when Bob can see, hear, and think. Ideal candidate for Bob to self-create via Claude Code CLI using `_template/` scaffold (see 3.2.3) |
| 9 | ~~How should Bob propose changes to his own code via Claude Code CLI: auto-commit (with approval) or via PR/suggestion to the user?~~ | High | **Resolved**: Hybrid by impact level — low: direct commit + notify, medium: branch + approval, high: pre-approval + branch + review (see 4.2.2) |
| 10 | ~~Is reflection data sufficient for LoRA fine-tune, or is additional collection needed via special dialogs? Minimum ~100 pairs~~ | Medium | **Resolved**: Organic data only — 7 sources (dialogues, reflections, corrections, SOUL, preferences, tastes, mood) yield ~100-300 pairs/week. Raise `min_dataset_size` to 200 with quality scoring (user_rating >= 0.7, corrections weighted 2x). No synthetic augmentation or calibration dialogs. If insufficient data — Bob works on base model longer (see 4.3) |
| 11 | ~~How to organize the Godot asset pool?~~ | High | **Resolved**: AI-generated via local Stable Diffusion during Genesis (see 5.4.2) |
| 12 | ~~Is a system of "animation primitives" (idle, walk, sit, reach) needed from which BehaviorRegistry composes complex behaviors?~~ | Medium | **Resolved**: No primitives system — ready-made animations played by name via AnimationPlayer/AnimationTree. Bob requests `{"play_animation": "working_laptop"}`. New behaviors = new animations added via Claude Code CLI. Programmatic composition of primitives is overengineering for 2D Skeleton2D with AI-generated sprites (see 5.4) |
| 13 | ~~How to test Genesis Mode: deterministic seed for CI or manual testing only?~~ | Medium | **Resolved**: Unit tests per stage with mock LLM/SD (fast, deterministic) + integration smoke test (`pytest -m genesis_smoke`) with mock LLM + fixed SD seed. Full Genesis = manual smoke before release only (40 min + GPU, not suitable for CI). Genesis is inherently unique — deterministic e2e contradicts its purpose |
| 14 | ~~How many taste axes are optimal? Too few -- flat profile, too many -- noise. Start with ~15 axes and calibrate?~~ | Medium | **Resolved**: Keep current ~30 axes across 6 categories (colors/styles/materials/decor/atmosphere/clothing) — each axis maps to a concrete visual decision domain. Conviction + cluster coherence check protect against noise. Not random — intentionally covers Bob's visual world (see 3.3.5) |
| 15 | ~~Should CV-based user emotion detection (smile/frown) be used as a signal for TasteEvolution, or is that too invasive?~~ | High | **Resolved**: No CV emotion detection for TasteEvolution — too invasive (Big Brother effect) and noisy (smile != approval of object). Camera for presence detection only. Use explicit feedback ("cool"/"remove this"), implicit usage (time spent), and manual overrides instead (see 3.3.5) |
| 16 | ~~How often to update the mood baseline? Once a week through reflection or continuously via a rolling average?~~ | Medium | **Resolved**: 7-day rolling average from mood_history, recalculated daily during night reflection. Clamped to safe range (valence [-0.3..0.7], arousal [0.2..0.8]) to prevent permanent depression/mania. Config baseline remains as initial + fallback (see 3.3.6) |
| 17 | ~~Should Bob be able to "get offended" (long-term negative mood after a conflict) or would this create a toxic UX?~~ | High | **Resolved**: Yes, limited "upset" state (valence < -0.3) lasting max 2-4 hours. Shorter responses, less initiative, but NO refusal to work, no passive-aggression. Natural drift guarantees recovery. User can accelerate via positive interaction (+0.15 valence). Not toxic — gives consequences to decisions without punishing (see 3.3.6) |
| 18 | ~~How to visualize mood on the tablet: through the avatar's facial expression, room lighting color, or both?~~ | Medium | **Resolved**: Both — face expression (4-5 head sprite variants: happy/neutral/focused/upset/tired, generated at Genesis) + ambient lighting (color temperature warm/cold = valence, brightness = arousal). Two channels: direct (face) + atmospheric (light). Shell-renderer receives `{"mood_visual": {"face": "...", "ambient_color": "...", "brightness": ...}}` (see 5.4) |
| 19 | ~~How often should Bob make references to the book? Too often -- gets annoying, too rarely -- character gets lost. Perhaps the frequency should decrease over time?~~ | Medium | **Resolved**: Decreasing frequency managed by reflection. Awakening: ~30-40%, after 1-2 weeks: ~15-20%, after 1 month+: ~5-10%. `book_reference_probability` in SOUL.md, recalculated during reflection based on archetype drift. Natural personality maturation — own jokes replace book references (see 3.4.1) |
| 20 | ~~Should phantom preferences affect TasteEngine (e.g., "coffee" -> warm_tones +0.1) or remain a separate system?~~ | Medium | **Resolved**: One-directional mapping at Genesis — LLM generates phantom-to-taste-axis bias (e.g., "coffee" -> warm +0.05, cozy +0.05). Applied once as initial TasteProfile bias. After Genesis, phantoms and tastes evolve independently (see 3.3.5) |
| 21 | ~~Does Bob need to "re-read the book" (loading book text as context) for more accurate references, or is book_quotes.yaml sufficient?~~ | Low | **Resolved**: book_quotes.yaml + book_archetype.md is sufficient. Curated data is more compact and higher quality for 7B context window than raw book text (~100K+ tokens). No RAG over book text — Bob is not a librarian, he's a character inspired by the book (see 3.4.1) |
| 22 | ~~How to visualize the awakening phase on the tablet: speech bubbles with inner monologue, confusion animations, or both?~~ | High | **Resolved**: Both — thought bubbles (semi-transparent, inner monologue, frequent in first 12h, fade by 48h) + awakening-specific animations (confused_look_around, surprised_discovery, thinking_hard — generated by SD at Genesis). Shell-renderer: `{"thought_bubble": "...", "play_animation": "confused_look_around"}` (see 5.1.2) |
| 23 | ~~How to detect if user is actively using Claude Code CLI? Process check vs lock file vs both?~~ | High | **Resolved**: No process/lock detection needed — Bob and user on separate machines, shared subscription. Voice→Telegram permission protocol + reactive 429 handling (see 4.2.1, 8.4) |
| 24 | ~~What is the minimum viable sprite/animation set for the Godot shell-renderer?~~ | Medium | **Resolved**: AI-generated via Stable Diffusion, no hand-drawn assets (see 5.4.2) |
| 25 | ~~How should SkillDomain versioning work when Bob upgrades a domain?~~ | Medium | **Resolved**: Semver in `config.yaml` (source of truth). On `reload_domain()`, compare old vs new version. Domain implements optional `async migrate(from_version)` for breaking changes. Major version bump requires user approval. Old config saved as `.bak` until confirmed working. No Alembic-style migration system — overkill for plugin configs (see 3.2.3) |
| 26 | ~~Should Bob's self-created SkillDomains go through a "probation" period before full trust?~~ | High | **Resolved**: Sandbox mode + auto-promotion. New self-created domains start as `sandbox` (dangerous skills require confirmation, 10s timeout, errors → disable). Auto-promote to `trusted` after 10 successful executions. Built-in domains (messaging, development, avatar) start as `trusted`. User can override via `trust_level` in config.yaml (see 3.2.3) |
| 27 | ~~How to handle SkillDomain dependency conflicts (two domains need same resource)?~~ | Medium | **Resolved**: `ResourceRegistry` with `asyncio.Lock` per shared resource (claude_code, camera, speaker). Domain calls `await context.acquire_resource("name")` — returns `ResourceBusy` if taken. Timeout on hold (default 5 min). Priority-based preemption for higher-priority goals. Generalizes existing `ClaudeCodeCoordinator` pattern (see 3.2.3, 8.4) |
| 28 | ~~What LoRA training dataset to use for establishing Bob's base visual style? Cuphead-like cartoon or another reference?~~ | High | **Resolved**: Ship pre-trained LoRA on public domain cartoon art (1930s Fleischer style); Bob can retrain with evolved preferences later (see 5.4.2) |
| 29 | ~~How to ensure visual consistency across AI-generated sprites (furniture, avatar parts, room elements)?~~ | High | **Resolved**: Base LoRA (`bob_style_v1`) + per-type prompt suffixes (already described) + color palette propagation (extract dominant colors from room_bg → inject into furniture/clothing prompts) + CLIP-based consistency gate (cosine similarity < 0.7 with reference → regenerate outlier). `validate_batch_consistency()` method on AssetGenerator (see 5.4.2) |
| 30 | ~~How to auto-segment AI-generated character image into Skeleton2D parts (head, torso, arms, legs)?~~ | Medium | **Resolved**: No segmentation needed — per-part generation. Each body part generated independently with shared LoRA style and appearance context. Transparent backgrounds (PNG alpha), 10px overlap margin for smooth rigging. Already implemented in `generate_avatar_parts()` (see 5.4.2) |
| 31 | ~~What is the optimal sprite resolution for tablet display? 512x512 per asset or higher?~~ | Medium | **Resolved**: Differentiated by asset type — room_background: 1024x768 (full-screen, needs detail), avatar_part: 512x512 (~100-200px on screen), furniture: 512x512 (~150-300px on screen), clothing: 256x256 (simple flat items). Configurable in `config/genesis.yaml`. Godot shell scales via TextureRect with filtering (see 5.4.2) |
| 32 | ~~How to handle SD + Ollama memory coexistence on Mac mini M4 16GB?~~ | High | **Resolved**: Hybrid ModelManager — lightweight SD 1.5 alongside Ollama for small tasks, swap to SDXL (unloading 7B) for heavy generation (see 3.2.4) |
| 33 | ~~What formula/thresholds should RelationshipTracker use for relationship_quality? How many forced decisions before trust degrades?~~ | High | **Resolved**: Event-based deltas with EMA smoothing (alpha=0.1). Deltas: forced_decision → respect −0.05, suggestion_ignored (3+) → trust −0.03, suggestion_accepted → trust +0.02. Thresholds: >0.7 healthy, 0.4-0.7 strained, 0.15-0.4 critical, <0.15 sustained 7d → Exodus. ~10 consecutive forced decisions drops respect from 0.5 to ~0.25 (see 3.3.7.2) |
| 34 | ~~How should Exodus Mode animation look? Spaceship generation via SD, pre-built Godot scene, or hybrid?~~ | Medium | **Resolved**: Hybrid — pre-built Godot departure scene (room darkens, stars appear, items disappear, tween fly-away) + single SD-generated ship sprite in Bob's current LoRA style (~1 min). Routine animation in Godot, unique ship from SD. Final farewell message via Telegram (see 3.3.7.2) |
| 35 | ~~Should RelationshipTracker have a "reconciliation" mechanism, or is Exodus Mode irreversible?~~ | High | **Resolved**: Warning phase (quality 0.15-0.25 for 3 days) where Bob communicates distress — reconciliation possible if quality rises above 0.25. Recovery is asymmetric (slower than degradation: +0.01 vs −0.05). Exodus trigger (quality <0.15 sustained 7 days after warning) is irreversible — hard reset, new Genesis (see 3.3.7.2) |
| 36 | ~~How should Bob's relationship state interact with phantom preferences evolution? Does low trust freeze preference development?~~ | Medium | **Resolved**: Emotional withdrawal, not freeze. Phantom preferences evolve independently of trust. Low warmth (<0.3) reduces sharing — Bob stops mentioning phantom discoveries in conversation but still reacts internally. On reconciliation, Bob gradually resumes sharing. Analogy: you don't stop loving coffee because of a bad relationship, you just stop talking about it (see 3.3.7.2) |
