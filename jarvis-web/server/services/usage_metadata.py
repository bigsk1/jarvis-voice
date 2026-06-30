"""Helpers for enriching LLM usage blobs persisted/emitted by the web chat."""


def enrich_usage_metadata(usage, provider=None, model=None):
    """Attach provider/model to usage blobs so the web UI can restore accurate stats."""
    if not usage:
        return usage
    enriched = dict(usage)
    if provider:
        enriched.setdefault('provider', provider)
    if model:
        enriched.setdefault('model', model)
    return enriched
