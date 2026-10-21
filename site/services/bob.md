---
title: bob
kind: service
---

# bob

**Kind:** service

Bob — Telegram-native companion agent: GUPPI process, LLM Tier 0/1 router with privacy redaction, SQLite+FTS5 memory, Higher Mind, Genesis, heartbeat. Two admin bots in one process (BOB-003): a MultiBotGateway (BotRegistry) polls both Bob and GUPPI, dedups cross-bot by (chat_id, message_id), and a central router dispatches by identity+scope — Bob lives in his forum topic, GUPPI is the gatekeeper in General with a visible unauthorized reject + owner commands. aiogram transport (native draft streaming + Rich Messages), owner/allowlist/chat-scope authz, resilient ticks, and a capability seam (registry + tool-loop) executed by GUPPI.

**Source:** `src/bob/`

## Public symbols

_None indexed._

## Relationships

- **Parts**: [bob-application](../domains/bob-application.md), [bob-domain](../domains/bob-domain.md), [bob-infrastructure](../domains/bob-infrastructure.md), [runtime](../services/runtime.md)

## Documentation

- [architecture.md](/docs/architecture.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="bob" :depth="1" height="60vh" />
</ClientOnly>

