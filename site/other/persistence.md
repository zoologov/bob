---
title: persistence
kind: component
---

# persistence

**Kind:** component

Persistence kernel — the shared `SqliteConnection` (open/WAL/foreign_keys/sqlite-vec load/`schema.sql`/kv/close) that the memory adapter and the 13 per-module durable stores read through the injected `connection` seam. Pure I/O: carries no memory/business logic — those realisations live in their owning modules' `adapters/` (BOB-062.2–.7b).

**Source:** `src/bob/infrastructure/persistence/`

## Public symbols

- `SqliteConnection`

## Relationships

- **part_of**: [bob-infrastructure](../domains/bob-infrastructure.md)
- **Used by**: [memory](../features/memory.md), [runtime](../services/runtime.md)

## Documentation

- [domains/infrastructure/features/persistence/SPEC.md](/docs/domains/infrastructure/features/persistence/SPEC.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="persistence" :depth="1" height="60vh" />
</ClientOnly>

