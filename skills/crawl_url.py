#!/usr/bin/env python3
"""
Jarvis Skill: Crawl URL
Uses Crawl4AI to fetch and extract clean markdown from any webpage.
More powerful than basic fetch - handles JavaScript, dynamic content, and complex sites.

Supports advanced features:
- Stealth mode (bypass bot detection)
- Custom wait conditions
- Content filtering
"""
import json
import os
import sys
import time

import requests

# Add lib to path for config_loader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import get_config_value, load_config
from http_client import http_request


def main():
    """Crawl URL and extract content."""
    # Load config (auto-detects mode)
    load_config()
    
    # Read input
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1
    if not isinstance(input_data, dict):
        return_error("Input must be a JSON object")
        return 1
    
    # Get configuration from config
    crawl4ai_url = get_config_value("CRAWL4AI_URL", "").rstrip("/")
    crawl4ai_api_key = get_config_value("CRAWL4AI_API_KEY", "").strip()
    
    if not crawl4ai_url:
        return_error("CRAWL4AI_URL not configured")
        return 1
    if not crawl4ai_api_key:
        return_error("CRAWL4AI_API_KEY not configured")
        return 1
    
    # Extract parameters
    url = input_data.get("url")
    urls = input_data.get("urls", [])
    
    # Support single URL or list
    if url and not urls:
        urls = [url]
    
    if not urls:
        return_error("URL is required")
        return 1

    if not isinstance(urls, list) or len(urls) > 10 or any(
        not isinstance(item, str) or not item for item in urls
    ):
        return_error("Provide between 1 and 10 public HTTP(S) URLs")
        return 1
    try:
        from stash_helper import SecurityError, validate_url
    except ImportError:
        return_error("URL security validation unavailable; crawl was not requested")
        return 1
    try:
        for target in urls:
            validate_url(target)
    except SecurityError as exc:
        return_error(f"URL blocked for security: {exc}")
        return 1

    if (
        input_data.get("js_code") or input_data.get("extraction_type") == "llm"
        or input_data.get("custom_patterns")
    ):
        return_error("The Crawl4AI API does not support JavaScript, LLM extraction, or custom regex patterns")
        return 1
    
    # Build headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {crawl4ai_api_key}",
    }
    
    # Build request body
    body = {
        "urls": urls,
    }
    
    # =========================================================================
    # Browser Config - uses REST API format: {"type": "BrowserConfig", "params": {...}}
    # =========================================================================
    browser_params = {"headless": True}
    
    # Stealth mode - bypass bot detection
    if input_data.get("stealth"):
        browser_params["enable_stealth"] = True
        browser_params["user_agent_mode"] = "random"
    
    # =========================================================================
    # Crawler Config - uses REST API format: {"type": "CrawlerRunConfig", "params": {...}}
    # =========================================================================
    crawler_params = {}
    
    # Wait for specific element before extracting
    if input_data.get("wait_for"):
        crawler_params["wait_for"] = f"css:{input_data['wait_for']}"
    
    # Page timeout (default 30s, max 60s for slow sites)
    page_timeout = min(input_data.get("page_timeout", 30000), 60000)
    crawler_params["page_timeout"] = page_timeout
    
    # Wait strategy for JavaScript-heavy sites
    # Options: "fast" (domcontentloaded), "normal" (load), "full" (networkidle - risky!)
    wait_strategy = input_data.get("wait_strategy", "normal")
    
    if input_data.get("wait_for_js") or wait_strategy != "fast":
        # Map strategy to Playwright wait_until values
        wait_until_map = {
            "fast": "domcontentloaded",  # DOM ready, fastest
            "normal": "load",             # All resources loaded (images, etc.)
            "full": "networkidle",        # No network for 500ms - DANGEROUS on live sites!
        }
        crawler_params["wait_until"] = wait_until_map.get(wait_strategy, "load")
        
        # Give JS time to render after page load
        delay = input_data.get("delay_before_return_html", 3.0)
        crawler_params["delay_before_return_html"] = min(delay, 10.0)  # Cap at 10s
    
    # Cache mode
    crawler_params["cache_mode"] = input_data.get("cache_mode", "bypass")
    if input_data.get("screenshot"):
        crawler_params["screenshot"] = True
    
    # Exclude noisy elements
    if input_data.get("exclude_tags"):
        crawler_params["excluded_tags"] = input_data["exclude_tags"]
    else:
        crawler_params["excluded_tags"] = ["nav", "footer", "aside", "script", "style"]
    
    # CSS selector to focus on specific content
    if input_data.get("css_selector"):
        crawler_params["css_selector"] = input_data["css_selector"]
    
    # =========================================================================
    # Extraction Strategies - REST API format with type/params wrappers
    # Ref: https://docs.crawl4ai.com/core/docker-deployment/
    # =========================================================================
    extraction_type = input_data.get("extraction_type")
    
    if extraction_type == "cosine":
        # Semantic similarity filtering - focuses on relevant content
        crawler_params["extraction_strategy"] = {
            "type": "CosineStrategy",
            "params": {
                "semantic_filter": input_data.get("semantic_filter", ""),
                "word_count_threshold": input_data.get("word_count_threshold", 10),
                "sim_threshold": input_data.get("similarity_threshold", 0.3),
                "top_k": input_data.get("top_k", 5),
            }
        }
        
    elif extraction_type == "regex":
        # Crawl4AI 0.9.5's default mask selects no built-ins. Send only the
        # reviewed families, using its integer IntFlag wire representation.
        builtins = {
            "email": 1,
            "phone": 2 | 4,
            "url": 8,
            "currency": 128,
            "percentage": 256,
            "date": 1024 | 2048,
        }
        patterns = input_data.get("regex_patterns", list(builtins))
        if (
            not isinstance(patterns, list) or not 1 <= len(patterns) <= len(builtins)
            or any(not isinstance(name, str) or name not in builtins for name in patterns)
        ):
            return_error("regex_patterns must be a nonempty list of email, phone, url, currency, date, percentage")
            return 1
        pattern_mask = 0
        for name in patterns:
            pattern_mask |= builtins[name]
        regex_params = {"input_format": "markdown", "pattern": pattern_mask}
        
        crawler_params["extraction_strategy"] = {
            "type": "RegexExtractionStrategy",
            "params": regex_params
        }
        
    elif extraction_type == "css":
        # CSS-based structured extraction (LLM-free)
        if input_data.get("css_schema"):
            crawler_params["extraction_strategy"] = {
                "type": "JsonCssExtractionStrategy",
                "params": {
                    "schema": {"type": "dict", "value": input_data["css_schema"]}
                }
            }
    
    # =========================================================================
    # Build final body with proper REST API type/params wrappers
    # =========================================================================
    body["browser_config"] = {
        "type": "BrowserConfig",
        "params": browser_params
    }
    body["crawler_config"] = {
        "type": "CrawlerRunConfig",
        "params": crawler_params
    }
    
    try:
        deadline = time.monotonic() + 75
        # Submit crawl job
        response = http_request(
            "POST",
            f"{crawl4ai_url}/crawl",
            headers=headers,
            json=body,
            timeout=60, deadline=deadline, allow_redirects=False, proxy_policy="off"
        )
        
        if response.status_code == 401:
            return_error("Authentication failed - check CRAWL4AI credentials")
            return 1
        
        if response.status_code == 403:
            return_error("Access forbidden - check API key")
            return 1
        
        if 300 <= response.status_code < 400:
            return_error("Crawl4AI redirected the authenticated request; configure its final API URL")
            return 1
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("success") is False:
            return_error("Crawl4AI reported a failed crawl")
            return 1
        
        # Extract markdown content
        # Handle both single result and array of results
        results = result.get("results", [result])
        if not isinstance(results, list):
            results = [results]
        
        all_content = []
        failed_urls = []
        for r in results:
            if not isinstance(r, dict):
                continue
            if r.get("success") is False:
                failed_urls.append(r.get("url", "unknown"))
                continue
            markdown = r.get("markdown") or r.get("fit_markdown") or r.get("raw_markdown", "")
            if isinstance(markdown, dict):
                markdown = markdown.get("fit_markdown") or markdown.get("raw_markdown", "")
            
            url_crawled = r.get("url", urls[0] if urls else "unknown")
            
            if markdown or r.get("extracted_content"):
                metadata = r.get("metadata") or {}
                content_item = {
                    "url": url_crawled,
                    "markdown": markdown[:10000],  # Limit size
                    "title": r.get("title") or (metadata.get("title", "") if isinstance(metadata, dict) else ""),
                    "success": r.get("success", True)
                }
                if len(markdown) > 10000:
                    content_item["truncated"] = True
                    content_item["original_characters"] = len(markdown)
                # Include extracted_content if extraction strategy produced results
                if r.get("extracted_content"):
                    content_item["extracted_content"] = r.get("extracted_content")
                
                all_content.append(content_item)
        
        if not all_content:
            return_error("No content extracted from URL")
            return 1
        
        # Build response
        if len(all_content) == 1:
            content = all_content[0]
            speech = f"Successfully crawled {content['url']}."
            if content.get("title"):
                speech += f" Title: {content['title']}"
        else:
            speech = f"Successfully crawled {len(all_content)} URLs."
        
        return_success(
            speech=speech,
            data={
                "results": all_content,
                "count": len(all_content),
                "failed_urls": failed_urls,
            }
        )
        return 0
        
    except requests.Timeout:
        return_error("Crawl request timed out")
        return 1
    except requests.RequestException as e:
        return_error(f"Crawl request failed: {str(e)}")
        return 1
    except Exception as e:
        return_error(f"Unexpected error: {str(e)}")
        return 1


def return_success(speech, data=None):
    """Return success response."""
    result = {
        "ok": True,
        "speech": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


def return_error(speech, data=None):
    """Return error response."""
    result = {
        "ok": False,
        "speech": speech,
        "error": speech
    }
    if data:
        result["data"] = data
    print(json.dumps(result))


if __name__ == "__main__":
    sys.exit(main())
