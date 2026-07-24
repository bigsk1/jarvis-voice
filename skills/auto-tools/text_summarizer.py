#!/usr/bin/env python3
"""
Text processing tool for summarization, keyword extraction, word/character counting, and sentiment analysis.
"""
import sys
import os
import json
import re
from collections import Counter
from typing import Any

# IMPORTANT: This tool lives in skills/auto-tools/, so go up 2 levels to reach lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config, get_config_value
from stash_helper import parse_stash_ref, resolve_file_path


def merge_llm_usage(total: dict[str, Any], usage: dict[str, Any] | None) -> None:
    """Accumulate provider usage across chunked summarization calls."""
    if not isinstance(usage, dict):
        return
    total["model_calls"] = total.get("model_calls", 0) + 1
    call_tokens = usage.get("total_tokens")
    if not isinstance(call_tokens, (int, float)):
        call_tokens = (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
    total["peak_context_tokens"] = max(total.get("peak_context_tokens", 0), call_tokens)
    for key in (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cost_usd",
        "cache_creation_tokens",
        "cache_read_tokens",
        "cache_write_cost_usd",
        "cache_read_cost_usd",
        "cache_cost_usd",
        "cache_savings_usd",
    ):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total[key] = total.get(key, 0) + value
    if usage.get("billing_mode"):
        total["billing_mode"] = usage["billing_mode"]
    if usage.get("cost_known") is False:
        total["cost_known"] = False
        total["has_unknown_cost"] = True
    for tool_name, count in (usage.get("server_side_tools") or {}).items():
        total.setdefault("server_side_tools", {})
        total["server_side_tools"][tool_name] = (
            total["server_side_tools"].get(tool_name, 0) + count
        )


def llm_chat_with_usage(
    provider,
    message: str,
    *,
    system_prompt: str,
    usage_total: dict[str, Any],
    provider_name: str,
    model: str,
    max_tokens: int,
    capture_usage: bool,
) -> str:
    """Call the provider without tools and retain its metering data."""
    if not capture_usage:
        return provider.chat(
            message,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        ) or ""
    text, _tool_call, usage, _thinking = provider.chat_with_tools(
        messages=[{"role": "user", "content": message}],
        tools=[],
        system_prompt=system_prompt,
    )
    merge_llm_usage(usage_total, usage)
    if isinstance(usage, dict):
        usage_total["provider"] = provider_name
        usage_total["model"] = model
    return text or ""

def count_stats(text: str) -> dict[str, int]:
    """Count words, characters, sentences, and paragraphs."""
    # Remove extra whitespace
    ' '.join(text.split())
    
    # Count characters (with and without spaces)
    chars_with_spaces = len(text)
    chars_without_spaces = len(text.replace(' ', '').replace('\n', '').replace('\t', ''))
    
    # Count words (split by whitespace)
    words = text.split()
    word_count = len(words)
    
    # Count sentences (basic: split by . ! ?)
    sentences = re.split(r'[.!?]+', text)
    sentence_count = len([s for s in sentences if s.strip()])
    
    # Count paragraphs (split by double newlines)
    paragraphs = re.split(r'\n\s*\n', text)
    paragraph_count = len([p for p in paragraphs if p.strip()])
    
    return {
        "words": word_count,
        "characters_with_spaces": chars_with_spaces,
        "characters_without_spaces": chars_without_spaces,
        "sentences": sentence_count,
        "paragraphs": paragraph_count
    }

def extract_keywords(text: str, top_n: int = 10) -> list[dict[str, Any]]:
    """Extract keywords using frequency analysis with stopword filtering."""
    # Basic stopwords list
    stopwords = set([
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he',
        'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was', 'will', 'with',
        'the', 'this', 'but', 'they', 'have', 'had', 'what', 'when', 'where', 'who',
        'which', 'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most',
        'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so',
        'than', 'too', 'very', 'can', 'just', 'should', 'now', 'i', 'you', 'we', 'our'
    ])
    
    # Tokenize and clean
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    
    # Filter stopwords and count
    filtered_words = [w for w in words if w not in stopwords]
    word_freq = Counter(filtered_words)
    
    # Get top N keywords
    top_keywords = word_freq.most_common(top_n)
    
    return [{"keyword": word, "frequency": count} for word, count in top_keywords]

def basic_sentiment(text: str) -> dict[str, Any]:
    """Basic sentiment analysis using keyword matching."""
    text_lower = text.lower()
    
    # Positive and negative word lists
    positive_words = set([
        'good', 'great', 'excellent', 'amazing', 'wonderful', 'fantastic', 'love',
        'happy', 'joy', 'beautiful', 'perfect', 'best', 'awesome', 'brilliant',
        'positive', 'success', 'successful', 'win', 'winner', 'pleased', 'delighted'
    ])
    
    negative_words = set([
        'bad', 'terrible', 'awful', 'horrible', 'hate', 'sad', 'angry', 'worst',
        'poor', 'negative', 'fail', 'failure', 'disappointed', 'disappointing',
        'unfortunate', 'problem', 'issue', 'wrong', 'error', 'difficult', 'hard'
    ])
    
    # Count positive and negative words
    words = re.findall(r'\b[a-z]+\b', text_lower)
    pos_count = sum(1 for w in words if w in positive_words)
    neg_count = sum(1 for w in words if w in negative_words)
    
    # Determine sentiment
    total_sentiment_words = pos_count + neg_count
    
    if total_sentiment_words == 0:
        sentiment = "neutral"
        confidence = 0.5
    elif pos_count > neg_count:
        sentiment = "positive"
        confidence = min(0.5 + (pos_count / (total_sentiment_words * 2)), 0.95)
    elif neg_count > pos_count:
        sentiment = "negative"
        confidence = min(0.5 + (neg_count / (total_sentiment_words * 2)), 0.95)
    else:
        sentiment = "neutral"
        confidence = 0.5
    
    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 2),
        "positive_words": pos_count,
        "negative_words": neg_count
    }

def summarize_text(text: str, num_sentences: int = 3) -> str:
    """Extractive summarization: select most important sentences."""
    # Split into sentences
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 20]
    
    if len(sentences) <= num_sentences:
        return text.strip()
    
    # Score sentences by word frequency (simple extractive method)
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    word_freq = Counter(words)
    
    # Score each sentence
    sentence_scores = []
    for sentence in sentences:
        sentence_words = re.findall(r'\b[a-z]{3,}\b', sentence.lower())
        score = sum(word_freq.get(w, 0) for w in sentence_words)
        sentence_scores.append((score, sentence))
    
    # Sort by score and take top N
    sentence_scores.sort(reverse=True)
    top_sentences = [s for _, s in sentence_scores[:num_sentences]]
    
    # Return in original order
    summary_sentences = []
    for sentence in sentences:
        if sentence in top_sentences:
            summary_sentences.append(sentence)
    
    return '. '.join(summary_sentences) + '.'

def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse common bool-ish values from JSON/tool args."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def normalize_operation(args: dict[str, Any]) -> str:
    """Accept older workflow aliases without breaking the public operation field."""
    operation = args.get('operation') or args.get('action') or 'summarize'
    aliases = {
        "summary": "summarize",
        "summarise": "summarize",
        "key_terms": "keywords",
        "num_keywords": "keywords",
        "word_count": "count",
        "stats": "count",
    }
    return aliases.get(str(operation).strip().lower(), str(operation).strip().lower())

def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into paragraph-aware chunks for LLM summarization."""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    paragraphs = re.split(r'\n\s*\n', text)

    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > max_chars:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start:start + max_chars])
            continue

        separator_len = 2 if current else 0
        if current and current_len + separator_len + len(paragraph) > max_chars:
            chunks.append("\n\n".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        else:
            current.append(paragraph)
            current_len += separator_len + len(paragraph)

    if current:
        chunks.append("\n\n".join(current))
    return chunks or [text[:max_chars]]

def select_chunks_for_llm(chunks: list[str], max_chunks: int) -> tuple[list[str], bool]:
    """Limit extreme inputs while keeping coverage across the document."""
    if len(chunks) <= max_chunks:
        return chunks, False
    if max_chunks <= 1:
        return [chunks[0]], True

    last_index = len(chunks) - 1
    indices = sorted({
        round(i * last_index / (max_chunks - 1))
        for i in range(max_chunks)
    })
    return [chunks[i] for i in indices], True

def create_llm_provider(args: dict[str, Any]):
    """Create the configured LLM provider for abstractive summarization."""
    from llm_provider import create_configured_provider

    return create_configured_provider(
        provider_override=args.get("llm_provider"),
        model_override=args.get("llm_model"),
        provider_config_keys=(
            "TEXT_SUMMARIZER_LLM_PROVIDER",
            "LLM_PROVIDER",
        ),
        model_config_keys=(
            "TEXT_SUMMARIZER_LLM_MODEL",
            "STASH_SUMMARIZE_MODEL",
        ),
        disable_server_side_tools=True,
    )

def llm_summary_prompt(
    text: str,
    *,
    max_words: int,
    style: str,
    focus: str,
    source_label: str,
    chunk_label: str = "",
) -> tuple[str, str]:
    """Build prompts for a faithful abstractive summary."""
    style_hint = {
        "bullets": "Use concise markdown bullets.",
        "executive": "Use a concise executive-summary style with clear takeaways.",
        "study_notes": "Use study-note style with key ideas and important details.",
        "detailed": "Use a detailed but compact structure with grouped takeaways.",
        "concise": "Use a compact paragraph or short bullets.",
    }.get(style, "Use a compact paragraph or short bullets.")

    focus_line = f"\nFocus especially on: {focus}" if focus else ""
    system_prompt = (
        "You are a precise summarizer for Jarvis. Summarize only the provided text. "
        "Preserve important names, numbers, dates, prices, claims, caveats, and conclusions. "
        "Do not invent facts. If the text is uncertain, keep that uncertainty."
    )
    user_prompt = f"""Summarize this text from {source_label}{chunk_label} in no more than {max_words} words.
{style_hint}{focus_line}

TEXT:
{text}
"""
    return system_prompt, user_prompt

def summarize_with_llm(text: str, args: dict[str, Any], source_info: dict[str, Any] | None = None) -> tuple[str | None, dict[str, Any]]:
    """Use configured LLM for long-form abstractive summarization."""
    source_info = source_info or {}
    max_words = int(args.get("max_words") or get_config_value("TEXT_SUMMARIZER_MAX_WORDS", "300"))
    style = str(args.get("summary_style") or args.get("style") or "concise").strip().lower()
    focus = str(args.get("focus") or "").strip()
    chunk_chars = int(args.get("llm_chunk_chars") or get_config_value("TEXT_SUMMARIZER_LLM_CHUNK_CHARS", "12000"))
    max_chunks = int(args.get("llm_max_chunks") or get_config_value("TEXT_SUMMARIZER_LLM_MAX_CHUNKS", "12"))
    max_tokens = int(args.get("llm_max_tokens") or get_config_value("TEXT_SUMMARIZER_LLM_MAX_TOKENS", "900"))
    capture_usage = parse_bool(args.get("_capture_usage"), default=False)
    source_label = source_info.get("stash_ref") or source_info.get("path") or "provided text"

    all_chunks = chunk_text(text, chunk_chars)
    chunks, was_chunk_limited = select_chunks_for_llm(all_chunks, max_chunks)
    meta = {
        "summary_method": "llm",
        "llm_used": False,
        "llm_provider": None,
        "llm_model": None,
        "input_characters": len(text),
        "chunks_total": len(all_chunks),
        "chunks_used": len(chunks),
        "chunk_limited": was_chunk_limited,
    }
    usage_total: dict[str, Any] = {}

    try:
        provider_name, model, provider = create_llm_provider(args)
        model = getattr(provider, "model", model)
        meta["llm_provider"] = provider_name
        meta["llm_model"] = model

        if len(chunks) == 1:
            system_prompt, user_prompt = llm_summary_prompt(
                chunks[0],
                max_words=max_words,
                style=style,
                focus=focus,
                source_label=source_label,
            )
            summary = llm_chat_with_usage(
                provider,
                user_prompt,
                system_prompt=system_prompt,
                usage_total=usage_total,
                provider_name=provider_name,
                model=model,
                max_tokens=max_tokens,
                capture_usage=capture_usage,
            )
            if summary and not summary.strip().lower().startswith("error:"):
                meta["llm_used"] = True
                meta["_usage"] = usage_total or None
                return summary.strip(), meta
            meta["_usage"] = usage_total or None
            return None, meta

        partials: list[str] = []
        per_chunk_words = max(120, min(260, max_words))
        for idx, chunk in enumerate(chunks, 1):
            system_prompt, user_prompt = llm_summary_prompt(
                chunk,
                max_words=per_chunk_words,
                style="detailed",
                focus=focus,
                source_label=source_label,
                chunk_label=f" (chunk {idx} of {len(chunks)})",
            )
            partial = llm_chat_with_usage(
                provider,
                user_prompt,
                system_prompt=system_prompt,
                usage_total=usage_total,
                provider_name=provider_name,
                model=model,
                max_tokens=max_tokens,
                capture_usage=capture_usage,
            )
            if not partial or partial.strip().lower().startswith("error:"):
                meta["_usage"] = usage_total or None
                return None, meta
            partials.append(partial.strip())

        combined = "\n\n".join(f"Chunk {idx}: {partial}" for idx, partial in enumerate(partials, 1))
        system_prompt, user_prompt = llm_summary_prompt(
            combined,
            max_words=max_words,
            style=style,
            focus=focus,
            source_label=f"chunk summaries for {source_label}",
        )
        final = llm_chat_with_usage(
            provider,
            user_prompt,
            system_prompt=system_prompt,
            usage_total=usage_total,
            provider_name=provider_name,
            model=model,
            max_tokens=max_tokens,
            capture_usage=capture_usage,
        )
        if final and not final.strip().lower().startswith("error:"):
            meta["llm_used"] = True
            meta["_usage"] = usage_total or None
            return final.strip(), meta
        meta["_usage"] = usage_total or None
        return None, meta
    except Exception as e:
        meta["llm_error"] = str(e)[:500]
        meta["_usage"] = usage_total or None
        return None, meta

def should_use_llm_summary(text: str, args: dict[str, Any]) -> bool:
    """Decide whether summarization should use the LLM path."""
    method = str(args.get("method") or args.get("summary_method") or "auto").strip().lower()
    if parse_bool(args.get("use_llm"), default=False):
        method = "llm"
    if method in {"extractive", "classic", "simple", "false", "off"}:
        return False
    if method in {"llm", "abstractive", "true", "on"}:
        return True
    min_chars = int(args.get("llm_min_chars") or get_config_value("TEXT_SUMMARIZER_LLM_MIN_CHARS", "4000"))
    return len(text) >= min_chars

def summarize_with_strategy(text: str, args: dict[str, Any], source_info: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Summarize with LLM for long inputs, falling back to extractive output."""
    num_sentences = int(args.get('num_sentences', 3))
    meta = {
        "summary_method": "extractive",
        "llm_used": False,
        "input_characters": len(text),
    }

    if should_use_llm_summary(text, args):
        llm_summary, llm_meta = summarize_with_llm(text, args, source_info)
        meta.update(llm_meta)
        if llm_summary:
            return llm_summary, meta
        meta["summary_method"] = "extractive"
        meta["llm_used"] = False
        meta["fallback_reason"] = meta.get("llm_error") or "llm_summary_unavailable"

    return summarize_text(text, num_sentences), meta

def load_text_from_stash(args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Load text directly from a stash ref or space/file pair."""
    stash_ref = (args.get('stash_ref') or '').strip()
    space_id = (args.get('space_id') or '').strip()
    file_id = (args.get('file_id') or '').strip()

    if not stash_ref and space_id and file_id:
        stash_ref = f"stash://{space_id}/{file_id}"
    if not stash_ref:
        return "", {}

    path = resolve_file_path(stash_ref=stash_ref)
    with open(path, 'r', encoding=args.get('encoding') or 'utf-8', errors='replace') as f:
        text = f.read()

    resolved_space_id, resolved_file_id = parse_stash_ref(stash_ref)
    return text, {
        "source": "stash",
        "stash_ref": stash_ref,
        "space_id": resolved_space_id,
        "file_id": resolved_file_id,
        "path": path,
        "characters_loaded": len(text),
    }

def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        text = args.get('text', '')
        operation = normalize_operation(args)  # summarize, keywords, count, sentiment
        source_info = {}

        if not text and (args.get('stash_ref') or (args.get('space_id') and args.get('file_id'))):
            text, source_info = load_text_from_stash(args)
        
        if not text:
            raise ValueError("No text provided. Provide text, stash_ref, or space_id+file_id.")
        
        result = {}
        speech = ""
        
        if operation == 'summarize':
            summary, summary_meta = summarize_with_strategy(text, args, source_info)
            usage = summary_meta.pop("_usage", None)
            result['summary'] = summary
            result['summary_meta'] = summary_meta
            if source_info:
                result['source'] = source_info
            speech = f"Summary: {summary}"
        
        elif operation == 'keywords':
            top_n = int(args.get('top_n') or args.get('num_keywords') or 10)
            keywords = extract_keywords(text, top_n)
            result['keywords'] = keywords
            if source_info:
                result['source'] = source_info
            top_words = [k['keyword'] for k in keywords[:5]]
            speech = f"Top keywords: {', '.join(top_words)}"
        
        elif operation == 'count':
            stats = count_stats(text)
            result['statistics'] = stats
            if source_info:
                result['source'] = source_info
            speech = f"Text contains {stats['words']} words, {stats['characters_with_spaces']} characters, {stats['sentences']} sentences, and {stats['paragraphs']} paragraphs"
        
        elif operation == 'sentiment':
            sentiment_result = basic_sentiment(text)
            result['sentiment'] = sentiment_result
            if source_info:
                result['source'] = source_info
            speech = f"Sentiment is {sentiment_result['sentiment']} with {int(sentiment_result['confidence']*100)}% confidence"
        
        else:
            raise ValueError(f"Unknown operation: {operation}")
        
        response = {
            "ok": True,
            "speech": speech,
            "data": result
        }
        if operation == "summarize" and usage:
            response["usage"] = usage
            if usage.get("server_side_tools"):
                response["server_side_tools"] = usage["server_side_tools"]
        print(json.dumps(response))
        
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "speech": f"Error: {e}"}))
        sys.exit(1)

if __name__ == "__main__":
    main()
