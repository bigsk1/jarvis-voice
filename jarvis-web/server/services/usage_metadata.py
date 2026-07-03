"""Helpers for enriching LLM usage blobs persisted/emitted by the web chat."""


def enrich_usage_metadata(usage, provider=None, model=None, mode=None):
    """Attach LLM identity to usage blobs so chat history remains self-describing."""
    if not usage:
        return usage
    enriched = dict(usage)
    if provider:
        enriched.setdefault('provider', provider)
    if model:
        enriched.setdefault('model', model)
    if mode:
        enriched.setdefault('mode', mode)
    return enriched


def format_usage_markdown(usage):
    """Return compact, human-readable per-response LLM identity and usage lines."""
    if not isinstance(usage, dict) or not usage:
        return []

    provider = usage.get('provider')
    model = usage.get('model')
    mode = usage.get('mode')
    identity = ' / '.join(str(value) for value in (provider, model) if value)
    if mode:
        identity = f"{identity} ({mode})" if identity else str(mode)

    lines = []
    if identity:
        lines.append(f"**LLM:** {identity}")

    input_tokens = usage.get('input_tokens')
    output_tokens = usage.get('output_tokens')
    model_calls = usage.get('model_calls')
    peak_context = usage.get('peak_context_tokens')
    details = []
    if isinstance(input_tokens, (int, float)) or isinstance(output_tokens, (int, float)):
        details.append(
            f"processed {int(input_tokens or 0):,} input / {int(output_tokens or 0):,} output"
        )
    if isinstance(model_calls, (int, float)):
        noun = 'call' if int(model_calls) == 1 else 'calls'
        details.append(f"{int(model_calls):,} model {noun}")
    if isinstance(peak_context, (int, float)):
        details.append(f"peak context {int(peak_context):,} tokens")
    if details:
        lines.append(f"**Usage:** {' | '.join(details)}")
    return lines
