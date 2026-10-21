---
title: llm
kind: component
---

# llm

**Kind:** component

LLM adapter — OpenAI-compatible provider for Tier 0/1 completion + tool-calling (Ollama/Qwen backend).

**Source:** `src/bob/infrastructure/llm/`

## Public symbols

- `FallbackLLMProvider`
- `OpenAICompatProvider`
- `ReportingLLMProvider`
- `ToolCallingFallbackLLMProvider`
- `ToolCallingReportingLLMProvider`
- `UnderstudyCheck`
- `UnderstudyEndpoint`
- `build_fallback_provider`
- `build_reporting_provider`
- `build_tier_providers`
- `build_web_search_provider`
- `probe_understudy`
- `understudy_endpoint`

## Relationships

- **part_of**: [bob-infrastructure](../domains/bob-infrastructure.md)
- **depends_on**: [bob-domain](../domains/bob-domain.md), [capabilities](../features/capabilities.md), [router](../features/router.md)
- **Used by**: [runtime](../services/runtime.md)

## Documentation

- [domains/infrastructure/features/llm/SPEC.md](/docs/domains/infrastructure/features/llm/SPEC.md)

## Graph

<ClientOnly>
  <ArchitectureMap focus="llm" :depth="1" height="60vh" />
</ClientOnly>

