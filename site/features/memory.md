---
title: memory
kind: feature
---

# memory

**Kind:** feature

Memory module («Bob remembers») — the full vertical capability in one place: `ports.py` (MemoryRepo, SelfActionRecorder, Embedder, Reranker — the read ports MemoryRecall/EpisodeReader and `Recalled` live in `kernel`, BOB-113) + pure `entities`, `usecases/` (extract facts, consolidate, dedup), and `adapters/` (FTS5/hybrid recall + local Ollama embedder/reranker). Domain-first slice BOB-062.2.

**Source:** `src/bob/memory/`

## Public symbols

- `CasualFloorRecall`
- `ClassifyWorkTalk`
- `ConsolidateMemory`
- `ConsolidationStore`
- `DedupFacts`
- `DedupStore`
- `Embedder`
- `EpisodicEvent`
- `ExtractFacts`
- `FactWriter`
- `Fts5MemoryRecall`
- `HybridMemoryRecall`
- `MemoryBackedSelfActionRecorder`
- `MemoryRepo`
- `MemoryVectorStore`
- `NoOpSelfActionRecorder`
- `OllamaEmbedder`
- `OllamaReranker`
- `Register`
- `RegisterResolver`
- `RenderedSelfAction`
- `Reranker`
- `SelfAction`
- `SelfActionEpisodeStore`
- `SelfActionKind`
- `SelfActionRecorder`
- `SemanticFact`
- `SqliteMemoryRepo`
- `WorkEpisode`
- `WorkTalkClassifier`
- `build_embedder`
- `build_reranker`
- `coding_terminal_kind`
- `describe_self_action`
- `filter_by_register`
- `may_recall_in_register`
- `parse_provenance_window`
- `parse_work_talk_verdict`
- `pool_has_work`
- `provenance_window`
- `register_ranked`
- `work_episode_event`

## Relationships

- **part_of**: [bob-domain](../domains/bob-domain.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md), [persistence](../other/persistence.md), [personality](../features/personality.md), [router](../features/router.md), [runtime-app](../features/runtime-app.md)
- **Used by**: [capabilities](../features/capabilities.md), [coding](../features/coding.md), [proactivity](../features/proactivity.md), [runtime](../services/runtime.md), [telegram](../other/telegram.md), [usecases](../features/usecases.md)

## Documentation

- [domains/memory/README.md](/docs/domains/memory/README.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="memory" :depth="1" height="60vh" />
</ClientOnly>

