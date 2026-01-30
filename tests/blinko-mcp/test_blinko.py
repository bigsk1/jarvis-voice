#!/usr/bin/env python3
"""Test Blinko MCP server to discover available tools."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
os.environ['MCP_DEBUG'] = '1'

from mcp_client import MCPRemoteClient
import json

print("Script starting...", flush=True)

from dotenv import load_dotenv

# Load environment variables from .env (optional, for local dev)
load_dotenv()

# Get API key from environment variable MCP_BLINKO_API_KEY
BLINKO_API_KEY = os.environ.get('MCP_BLINKO_API_KEY')
if not BLINKO_API_KEY:
    raise RuntimeError("MCP_BLINKO_API_KEY not set in environment or .env file.")

# Connect to Blinko MCP server
client = MCPRemoteClient(
    name='blinko',
    url='http://localhost:1111/sse',
    transport_type='sse',
    headers={
        'Authorization': f'Bearer {BLINKO_API_KEY}'
    }
)

try:
    print('Starting client...', flush=True)
    client.start()
    print('Client started, listing tools...', flush=True)
    tools = client.list_tools()
    print(f'Got {len(tools)} tools', flush=True)
    print(json.dumps(tools, indent=2), flush=True)
    client.stop()
except Exception as e:
    print(f'Error: {e}', flush=True)
    import traceback
    traceback.print_exc()
