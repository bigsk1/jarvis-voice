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


def main():
    """Crawl URL and extract content."""
    # Read input
    try:
        input_data = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    except (json.JSONDecodeError, IndexError):
        return_error("Invalid JSON input")
        return 1
    
    # Get configuration from environment
    crawl4ai_url = os.environ.get("CRAWL4AI_URL", "").rstrip("/")
    crawl4ai_user = os.environ.get("CRAWL4AI_USER", "")
    crawl4ai_pass = os.environ.get("CRAWL4AI_PASS", "")
    crawl4ai_api_key = os.environ.get("CRAWL4AI_API_KEY", "")
    
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
    
    # Browser config (stealth, user agent, etc.)
    browser_config = {}
    crawler_config = {}  # API uses crawler_config, not crawler_params!
    
    # Stealth mode - bypass bot detection
    if input_data.get("stealth"):
        browser_config["enable_stealth"] = True
        browser_config["user_agent_mode"] = "random"
    
    # Wait for specific element before extracting
    if input_data.get("wait_for"):
        crawler_config["wait_for"] = f"css:{input_data['wait_for']}"
    
    # Wait for JavaScript to fully load
    if input_data.get("wait_for_js"):
        crawler_config["wait_until"] = "networkidle"
        crawler_config["delay_before_return_html"] = 2.0
    
    # Execute JavaScript (e.g., dismiss modals)
    if input_data.get("js_code"):
        crawler_config["js_code"] = input_data["js_code"]
    
    # Exclude noisy elements
    if input_data.get("exclude_tags"):
        crawler_config["excluded_tags"] = input_data["exclude_tags"]
    else:
        # Default: exclude common noise
        crawler_config["excluded_tags"] = ["nav", "footer", "aside", "script", "style"]
    
    # CSS selector to focus on specific content
    if input_data.get("css_selector"):
        crawler_config["css_selector"] = input_data["css_selector"]
    
    # Add configs to body
    if browser_config:
        body["browser_config"] = browser_config
    if crawler_config:
        body["crawler_config"] = crawler_config  # Correct key name!
    
    if input_data.get("screenshot"):
        body["screenshot"] = True
    
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
                all_content.append({
                    "url": url_crawled,
                    "markdown": markdown[:10000],  # Limit size
                    "title": r.get("title", ""),
                    "success": r.get("success", True)
                })
        
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

