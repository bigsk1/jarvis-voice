# Embedding Health Checks

Jarvis uses the versioned Ollama artifact `bigsk1/jarvis-embedding:bf16-v1` at
768 dimensions for both cloud and local databases. It is an exact BF16 copy of
EmbeddingGemma. Dimension equality alone is insufficient: health checks also
require the exact model digest, official prompt profile, prompt role,
input-format version, and a completed namespace state.

## Commands

```bash
# Preflight only: verify configured Ollama hosts, model tag, and digest without
# opening or creating Memory/Intelligence databases.
./bin/check-embeddings-health.py --both --runtime-only

# Full runtime + Memory/Tool RAG database fingerprint/vector health.
./bin/check-embeddings-health.py cloud
./bin/check-embeddings-health.py local
./bin/check-embeddings-health.py --both
./bin/check-embeddings-health.py --both --json

./bin/check-intelligence-health.py cloud
./bin/check-intelligence-health.py local
./bin/check-intelligence-health.py --both --json
```

The runtime-only preflight is the appropriate fresh-install check after editing
`config/cloud.env` and `config/local.env`. Jarvis does not assume Ollama runs on
localhost and does not install Ollama or pull the Jarvis model automatically.

Memory health covers:

- `memory.knowledge_base.embedding`
- `memory.tool_definitions.embedding`
- all vector dimensions and missing vectors
- configured Ollama hosts and the exact model digest

Intelligence health covers:

- `intelligence.experiences.query_embedding`
- `intelligence.experiences.context_embedding`
- `intelligence.experiences.outcome_embedding`
- `intelligence.insights.insight_embedding`
- `intelligence.insights.pattern_embedding`
- learning statistics and reflection-queue warnings

## Failure behavior

An absent fingerprint with existing vectors, a mismatched field, or a
`rebuilding` state disables semantic access to that namespace. Memory retains
FTS5/keyword fallback; Intelligence does not return results from incompatible
vectors. Hash-generated fallback vectors are never persisted or queried.

The most common recovery is:

```bash
./bin/rebuild-embeddings cloud
./bin/rebuild-embeddings local
```

The rebuild command backs up each database, batches requests through
`OLLAMA_BASE_URL`, checkpoints each namespace, and uses Ollama's default device
placement. It does not force CPU execution.

For an older public clone where data preservation is unnecessary, delete the
incompatible database and restart instead. Jarvis intentionally has no
OpenAI/Nomic compatibility or automatic legacy-vector migration path.

## Host mismatch

Every reachable fallback host that exposes the configured model must match
`OLLAMA_EMBEDDING_MODEL_DIGEST`. A different digest disables embeddings rather
than allowing host failover to mix vector spaces. Unavailable hosts and hosts
without the model are reported separately; at least one verified host is
required.

## After rebuilding

Run both health commands again, then evaluate retrieval thresholds against the
labeled bake-off corpus before changing production defaults. A quantized model
is a new artifact fingerprint and requires another complete rebuild even when
its output shape is also 768D.
