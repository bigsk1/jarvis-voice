#!/usr/bin/env python3
"""
Jarvis Skill: Crawl URL
Uses Crawl4AI to fetch and extract clean markdown from any webpage.
More powerful than basic fetch - handles JavaScript, dynamic content, and complex sites.

Supports advanced features:
- Stealth mode (bypass bot detection)
- Custom wait conditions
- JavaScript execution
- Content filtering
"""
import sys
import os
import json
import requests
from base64 import b64encode

# Add lib to path for config_loader
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config, get_config_value


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
    
    # Get configuration from config
    crawl4ai_url = get_config_value("CRAWL4AI_URL", "").rstrip("/")
    crawl4ai_user = get_config_value("CRAWL4AI_USER", "")
    crawl4ai_pass = get_config_value("CRAWL4AI_PASS", "")
    crawl4ai_api_key = get_config_value("CRAWL4AI_API_KEY", "")
    
    if not crawl4ai_url:
        return_error("CRAWL4AI_URL not configured")
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
    
    # Build headers
    headers = {
        "Content-Type": "application/json"
    }
    
    # Add basic auth if configured
    if crawl4ai_user and crawl4ai_pass:
        auth_string = b64encode(f"{crawl4ai_user}:{crawl4ai_pass}".encode()).decode()
        headers["Authorization"] = f"Basic {auth_string}"
    
    # Add API key
    if crawl4ai_api_key:
        headers["x-api-key"] = crawl4ai_api_key
    
    # Build request body
    body = {
        "urls": urls,
        "priority": input_data.get("priority", 10),
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
    
    # SECURITY: js_code parameter - only allow safe, pre-approved snippets
    if input_data.get("js_code"):
        SAFE_JS_SNIPPETS = {
            "dismiss_modal": "document.querySelector('.modal-close, [data-dismiss=\"modal\"]')?.click()",
            "scroll_down": "window.scrollTo(0, document.body.scrollHeight)",
            "accept_cookies": "document.querySelector('[data-accept-cookies], .accept-cookies, #accept-cookies')?.click()",
        }
        js_code = input_data["js_code"]
        if js_code in SAFE_JS_SNIPPETS:
            crawler_params["js_code"] = SAFE_JS_SNIPPETS[js_code]
        else:
            import logging
            logging.warning(f"Blocked arbitrary js_code execution: {js_code[:100]}")
    
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
    
    if extraction_type == "llm":
        # LLM-based extraction - uses OpenAI/etc on Crawl4AI server
        llm_params = {
            "instruction": input_data.get("extraction_instruction", "Extract key information from this page"),
            "extraction_type": "schema" if input_data.get("extraction_schema") else "block",
            "apply_chunking": True,
            "chunk_token_threshold": input_data.get("chunk_threshold", 4000),
        }
        # Optional: provider override (defaults to server's configured provider)
        if input_data.get("llm_provider"):
            llm_params["provider"] = input_data["llm_provider"]
        # Optional: structured schema - wrap as {"type": "dict", "value": {...}}
        if input_data.get("extraction_schema"):
            llm_params["schema"] = {"type": "dict", "value": input_data["extraction_schema"]}
        
        crawler_params["extraction_strategy"] = {
            "type": "LLMExtractionStrategy",
            "params": llm_params
        }
        
    elif extraction_type == "cosine":
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
        # Fast pattern-based extraction - custom patterns wrapped as dict
        regex_params = {"input_format": "fit_html"}
        if input_data.get("custom_patterns"):
            regex_params["custom"] = {"type": "dict", "value": input_data["custom_patterns"]}
        
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
    
    if input_data.get("screenshot"):
        body["screenshot"] = True
    
    # Track if extraction was requested (for fallback handling)
    extraction_requested = extraction_type is not None
    
    try:
        # Submit crawl job
        response = requests.post(
            f"{crawl4ai_url}/crawl",
            headers=headers,
            json=body,
            timeout=60
        )
        
        if response.status_code == 401:
            return_error("Authentication failed - check CRAWL4AI credentials")
            return 1
        
        if response.status_code == 403:
            return_error("Access forbidden - check API key")
            return 1
        
        # If extraction caused a 500 error, retry without it
        if response.status_code == 500 and extraction_requested:
            import logging
            logging.warning(f"Extraction strategy failed (500), retrying without extraction...")
            # Remove extraction_strategy and retry
            if "extraction_strategy" in crawler_params:
                del crawler_params["extraction_strategy"]
                body["crawler_config"]["params"] = crawler_params
            response = requests.post(
                f"{crawl4ai_url}/crawl",
                headers=headers,
                json=body,
                timeout=60
            )
        
        response.raise_for_status()
        result = response.json()
        
        # Handle async task - poll for result
        task_id = result.get("task_id")
        if task_id:
            # Poll for completion
            import time
            max_attempts = 30  # 30 seconds max
            for _ in range(max_attempts):
                time.sleep(1)
                status_resp = requests.get(
                    f"{crawl4ai_url}/task/{task_id}",
                    headers=headers,
                    timeout=30
                )
                status_resp.raise_for_status()
                status = status_resp.json()
                
                if status.get("status") == "completed":
                    result = status.get("result", status)
                    break
                elif status.get("status") == "failed":
                    return_error(f"Crawl failed: {status.get('error', 'Unknown error')}")
                    return 1
            else:
                return_error("Crawl timed out after 30 seconds")
                return 1
        
        # Extract markdown content
        # Handle both single result and array of results
        results = result.get("results", [result])
        if not isinstance(results, list):
            results = [results]
        
        all_content = []
        for r in results:
            markdown = r.get("markdown") or r.get("fit_markdown") or r.get("raw_markdown", "")
            if isinstance(markdown, dict):
                markdown = markdown.get("fit_markdown") or markdown.get("raw_markdown", "")
            
            url_crawled = r.get("url", urls[0] if urls else "unknown")
            
            if markdown:
                content_item = {
                    "url": url_crawled,
                    "markdown": markdown[:10000],  # Limit size
                    "title": r.get("title", ""),
                    "success": r.get("success", True)
                }
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
                "count": len(all_content)
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

