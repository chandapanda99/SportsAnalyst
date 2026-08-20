# Contributing plugins

A sport plugin implements `SportPlugin` and owns five things: entity resolution, dataset semantics, registered tool definitions, a deterministic default plan, and analysis execution.

New analytical capabilities must:

1. Accept typed, bounded inputs.
2. Produce versioned `AggregateEvidence` or `PlayEvidence`.
3. Include source manifest IDs, row-set hashes, tool versions, and caveats.
4. Be deterministic for identical inputs, except explicitly seeded statistical procedures.
5. Include synthetic unit tests and at least one evaluation case.
6. Avoid model-generated executable code and host filesystem or network access.

Provider adapters implement `ModelProvider`, return a LangChain-compatible chat model, and must not serialize credentials into configuration or report artifacts.

Future sandbox packages may implement `CustomAnalysisRunner`, but that interface is not exposed to the v1 agent and is intentionally disabled in the core distribution.
