# Jarvis Embedding Ollama Artifact

Jarvis uses one versioned Ollama embedding artifact in cloud and local modes:

```text
bigsk1/jarvis-embedding:bf16-v1
```

Pull it on every daemon listed in `OLLAMA_BASE_URL`:

```bash
ollama pull bigsk1/jarvis-embedding:bf16-v1
```

## Artifact identity

| Field | Pinned value |
|---|---|
| Registry tag | `bigsk1/jarvis-embedding:bf16-v1` |
| Ollama manifest SHA-256 | `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1` |
| Model layer SHA-256 | `0800cbac9c2064dde519420e75e512a83cb360de3ad5df176185dc69652fc515` |
| Upstream artifact | Ollama `embeddinggemma:300m-bf16` |
| Architecture | Gemma 3 embedding model |
| Parameters | 307.58M |
| Quantization | BF16 |
| Dimensions | 768 |
| Context window | 2048 tokens |
| Pooling | Mean |

The tag was published as an exact manifest copy of the upstream BF16 artifact,
including its Gemma Terms of Use license layer, template, parameters, and model
weights. Representative query, document, and similarity inputs produced
bit-for-bit identical normalized vectors before publication.

## Hugging Face recovery mirror

The exact GGUF model layer and Ollama provenance artifacts are also archived in
the public, automatically gated Hugging Face repository:

```text
https://huggingface.co/bigsk1/jarvis-embedding-GGUF
```

The mirror contains the 621,867,104-byte BF16 GGUF, the original Ollama
manifest, config and parameter layers, the bundled Gemma terms, the required
redistribution notice, a recovery Modelfile, and SHA-256 checksums. Hugging Face
is a disaster-recovery source, not a second Jarvis runtime provider; Jarvis
continues to call Ollama exclusively.

An Ollama 0.32.13 recovery test produced bit-for-bit identical 768-dimensional
vectors for representative query, document, and similarity inputs. However,
`ollama create` reserialized the GGUF and added a template layer, so the rebuilt
Ollama manifest digest differed from the pinned digest. A rebuild from the
Hugging Face Modelfile must therefore use a new immutable tag, update the Jarvis
fingerprint, and re-embed every persisted namespace. It must not replace the
existing `bf16-v1` identity.

## Immutability policy

Do not overwrite `bf16-v1`. A future weight, template, parameter, or license
change must use a new versioned tag such as `bf16-v2`, update
`OLLAMA_EMBEDDING_MODEL_DIGEST`, and rebuild every persisted embedding
namespace. Jarvis verifies both the exact tag and manifest digest and fails
closed rather than mixing artifacts.

There is intentionally no runtime dependency on the upstream
`embeddinggemma:latest` tag and no Jarvis `latest` tag in the configuration.

## Verification

After pulling the model, verify every configured host without opening or
creating a database:

```bash
./bin/check-embeddings-health.py --both --runtime-only
```

To inspect one daemon directly:

```bash
curl -fsS http://localhost:11434/api/tags \
  | jq '.models[] | select(.name == "bigsk1/jarvis-embedding:bf16-v1") \
        | {name, digest, size, details}'
```

The reported `digest` must equal the pinned manifest SHA-256 above.
