# Cloud and Local Database System

Jarvis keeps separate cloud and local data sets:

```text
data/jarvis_memory.db
data/jarvis_memory_local.db
data/jarvis_intelligence.db
data/jarvis_intelligence_local.db
```

The separation preserves intentional mode-specific data and maintenance state.
It no longer represents different embedding providers. Every database uses the
same Ollama Jarvis Embedding contract, based on the pinned EmbeddingGemma BF16 artifact:

```text
provider:       ollama
model:          bigsk1/jarvis-embedding:bf16-v1
dimensions:     768
prompt profile: embeddinggemma-official-v1
```

The exact model digest, prompt role, and input-format version are recorded for
each vector namespace in `embedding_metadata`.

## Required configuration

Put the same values in `config/cloud.env` and `config/local.env`:

```bash
OLLAMA_BASE_URL="http://localhost:11434"
OLLAMA_EMBEDDING_MODEL="bigsk1/jarvis-embedding:bf16-v1"
OLLAMA_EMBEDDING_MODEL_DIGEST="85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1"
OLLAMA_EMBEDDING_CONTEXT_WINDOW=2048
```

Pull the model on every configured fallback host:

```bash
ollama pull bigsk1/jarvis-embedding:bf16-v1
```

Jarvis verifies each reachable host against the configured digest before using
it. Ollama selects its normal GPU/CPU placement; Jarvis does not force CPU
execution.

## Compatibility break

Databases created with OpenAI, Nomic, missing metadata, a different model
digest, or an incomplete rebuild are incompatible. Jarvis does not mix or
automatically convert those vectors.

For a clean install, delete the incompatible database and restart. To preserve
the text and learning records in an operator-owned database, run:

```bash
./bin/rebuild-embeddings cloud
./bin/rebuild-embeddings local
# or
./bin/rebuild-embeddings both
```

The command:

- creates a SQLite-consistent backup under `data/backups/`;
- sends batches through the configured `OLLAMA_BASE_URL` hosts;
- uses query/document/similarity prompts appropriate to each namespace;
- checkpoints progress by row ID;
- leaves a namespace in `rebuilding` state after interruption;
- marks it `complete` only after all vectors are written.

Use `--force` only to rebuild an already-current fingerprint.

## Fail-closed behavior

Semantic reads and embedding writes require an exact namespace fingerprint.
When the fingerprint is missing, mismatched, or rebuilding:

- Memory search falls back to FTS5/keyword retrieval;
- Tool RAG falls back to keyword matching;
- Intelligence returns no semantic insight matches;
- health checks fail with the incompatible namespace and recovery command;
- startup skips Tool RAG embedding sync.

This prevents same-size but semantically incompatible vectors from being
compared. Vector similarity also rejects unequal dimensions instead of silently
zipping the shorter vector.

## Sync boundaries

`./bin/sync-memory-db.py` remains the automatic portable-memory sync path.
It copies newer memory text and regenerates changed or missing target vectors.
Conversation history, user-model rows, alerts, and reminders remain non-vector
sync data. If the target memory namespace is incompatible, vector memory sync is
skipped while the non-vector sync phases may still run.

`tool_definitions` is not copied by memory sync. Run Tool RAG sync for each
database:

```bash
source "$HOME/jarvis-venv/bin/activate"
./bin/sync-tools.py cloud
./bin/sync-tools.py local
```

Intelligence sync remains a separate, manual, additive operation:

```bash
./bin/sync-intelligence-db.py local   # cloud to local
./bin/sync-intelligence-db.py cloud   # local to cloud
```

It preserves target-only learning and excludes `meta_knowledge`, which belongs
to each database's own maintenance history. An incompatible target fingerprint
aborts Intelligence sync before learning rows are changed.

## Health checks

```bash
./bin/check-embeddings-health.py --both
./bin/check-intelligence-health.py --both
```

Health checks validate the model host, digest, every namespace fingerprint,
every stored vector dimension, and missing required vectors.

Similarity thresholds should be retuned after the EmbeddingGemma bake-off:

```bash
SEMANTIC_SIMILARITY_THRESHOLD=0.40
AUTO_MEMORY_SIMILARITY_THRESHOLD=0.87
TOOL_SIMILARITY_THRESHOLD=0.30
TOOL_SIMILARITY_THRESHOLD_FULL=0.45
```

Keep the initial values until measured retrieval results justify changing them.
