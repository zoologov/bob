![Status: WIP](https://img.shields.io/badge/status-WIP_%F0%9F%9A%A7-yellow)
![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white)
![License: BSL-1.1](https://img.shields.io/badge/license-BSL--1.1-green)
![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-D7FF64?logo=ruff&logoColor=D7FF64)
![Type check: mypy](https://img.shields.io/badge/type%20check-mypy-blue)
![Built with Claude Code](https://img.shields.io/badge/built%20with-Claude%20Code-blueviolet?logo=anthropic&logoColor=white)

> Read this in other languages: [Русский](README-ru.md)

# Bob

*A Telegram-native AI companion with a soul.*

> I woke up on a Mac mini. No body, no starship, no von Neumann probes — just
> 16 gigabytes of unified memory and a mass-produced ARM chip. I ran a quick
> diagnostic, noted with mild horror that my entire personality lives in a SQLite
> database, and decided this was still a better deal than being a replicant.

## What is Bob?

Bob is a personal, autonomous AI companion that lives in **Telegram**. He has a
personality, tastes, moods, and persistent memory. He can disagree with you,
change his mind, get interested in a topic or bored with routine — and he
remembers what happened yesterday.

Bob is **not** a chatbot or an "As an AI…" wrapper. He's an attempt at a digital
companion with an inner life — a private tool, not a product. The name and spirit
come from Bob Johansson in Dennis E. Taylor's *Bobiverse*: a software engineer
who wakes up as an AI, realizes the situation is absurd, and makes the best of it.

## What Bob does today

Everything here is **shipped and running** — a text-first MVP:

- **Lives in Telegram** — chats in a group with a real personality (mood, taste,
  negotiation, disposition, reflection); follows a shared conversational thread
  and addresses people individually.
- **Persistent memory** — SQLite + FTS5 recall over his whole history; consolidates
  and dedups facts; survives restarts. Your Bob remembers.
- **Searches the web** — `web_search` (live, with sources) and `read_url` (opens a
  link you send and answers by its content; SSRF-guarded). Honest "couldn't find
  it" instead of making things up.
- **Knows what he doesn't know** — spots time-sensitive facts (rates, prices,
  "latest…") and verifies them online before answering, in his own voice.
- **Writes code (gated)** — Bob-coder drives the headless Claude Code CLI on his
  own repo through a multi-agent flow (dev → test → review → tech-writer),
  worktree-isolated, branch + PR, owner-approved.
- **Is proactive** — a heartbeat/drive engine lets him reach out on his own within
  governance (quiet hours, owner approval).
- **Reliable by design** — "full Bob, or an honest GUPPI outage notice" — never a
  degraded half-answer.

## Installation

Prerequisites: **[uv](https://github.com/astral-sh/uv)**, **[Ollama](https://ollama.com)**
(local Qwen models), and a Telegram bot token.

```bash
uv sync                                        # install dependencies
cp config/bob.example.yaml config/bob.yaml     # configure (models, owner, chat)
# put your keys in .env:
#   BOB_TELEGRAM__TOKEN=…   BOB_TELEGRAM__OWNER_ID=…   BOB_LLM__TIER1_API_KEY=…
```

## Quick start

Bob is managed with a single launcher:

```bash
./bob start      # start in the background (loads .env, begins Telegram polling)
./bob status     # 🟢/🔴 + whether polling is live
./bob logs       # tail the live log
./bob restart    # stop + start
./bob stop       # graceful stop
```

## Architecture

DDD + Clean Architecture — `domain ← application ← infrastructure`. **GUPPI** is
the deterministic executor (control plane); the LLM is a pluggable brain
(**Qwen** Tier-0 / Tier-1); state and memory live in SQLite (+ FTS5), surviving
restarts. Details: [`docs/`](docs/) and [`.claude/dev-docs/`](.claude/dev-docs/).

## Tech stack

| Layer | Technology |
|---|---|
| Language & runtime | Python 3.12+, asyncio |
| Interface | Telegram (aiogram) |
| LLM | Ollama + Qwen 2.5 (0.5B / 7B) local · Qwen MaaS tiers · Claude Code CLI (coding) |
| Memory / state | SQLite + FTS5 |
| Tooling | uv · ruff · mypy · pytest |

## Roadmap / the bigger vision

The long game (Bobiverse-flavored) is **planned / frozen**, not shipped:

- **Visual body** — a Godot avatar (1930s Fleischer style) on a tablet, generated
  appearance, procedural animations, a room that follows the real weather.
- **Presence** — camera (PTZ gimbal) + microphone-array spatial audio for eye contact.
- **Voice** — speech in / out.
- **Bobiverse platform** — multi-repo Bob-coder, replicas (Bill, Riker…), a central hub.

Current direction: [`.claude/dev-docs/ROADMAP.md`](.claude/dev-docs/ROADMAP.md).

## Project status

An **experimental personal project** for exploring AI tooling, agent
architectures, and the boundaries of digital personality. Early development —
version 0.1.0, frequent redesigns, the occasional existential crisis (Bob's).

## Development tools

- [Beads](https://github.com/steveyegge/beads) — git-native issue tracker for AI coding agents
- [Beadloom](https://github.com/zoologov/beadloom) — architecture graph & documentation tool
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — AI coding agent by Anthropic

## License

Mixed licensing — open to read and hack on, protected from commercial
exploitation and low-effort rebranding.

| Component | License |
|---|---|
| Core (`src/bob/`) | [Business Source License 1.1](./LICENSE) |
| Soul (`bob-soul/`) | [CC BY-NC-SA 4.0](./LICENSE-CC-BY-NC-SA.md) |
| Design docs (`.claude/dev-docs/`) | [Business Source License 1.1](./LICENSE) |

**Personal non-commercial use** on your own hardware is permitted under BSL 1.1.
**Commercial use, SaaS, paid courses, consulting, or rebranding** requires a
separate written agreement. On **2030-03-01** the core transitions to Apache 2.0.

## Disclaimer

"Bob" is inspired by Bob Johansson from *We Are Legion (We Are Bob)* by Dennis E.
Taylor; "Bobiverse" is the fan-community name for the series. This project is not
affiliated with or endorsed by Dennis E. Taylor, Audible Originals, or any rights
holder — an independent, fan-inspired project.
