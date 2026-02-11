"""
Tool Discovery Service
Auto-loads tools from skills/*.tool.json AND memory_db (includes MCP tools)
"""
import json
import sys
from pathlib import Path
from ..config import SKILLS_PATH, JARVIS_ROOT, get_web_setting


class ToolDiscoveryService:
    """Discovers and manages available Jarvis tools"""
    
    def __init__(self, skills_path: Path = None):
        self.skills_path = skills_path or SKILLS_PATH
        self.tools: dict[str, dict] = {}
        self._load_tools()
    
    def _load_tools(self):
        """Load all tool definitions from skills folder AND memory_db"""
        self.tools = {}
        
        # Get blocked tools for web
        blocked_tools = set(get_web_setting('tools.blocked', []))
        
        # 1. Load local tools from skills/**/*.tool.json (including subdirectories like auto-tools/)
        if self.skills_path.exists():
            for tool_file in self.skills_path.glob('**/*.tool.json'):
                try:
                    with open(tool_file, 'r') as f:
                        tool = json.load(f)
                    
                    name = tool.get('name', tool_file.stem.replace('.tool', ''))
                    is_blocked = name in blocked_tools
                    
                    # Include all tools (enabled or blocked for visibility)
                    if tool.get('enabled', True) or is_blocked:
                        self.tools[name] = {
                            'name': name,
                            'description': tool.get('description', ''),
                            'enabled': tool.get('enabled', True) and not is_blocked,
                            'blocked': is_blocked,
                            'source': 'local',
                            'parameters': tool.get('parameters', {}),
                            'script': tool.get('script', ''),
                            'file': str(tool_file)
                        }
                except Exception as e:
                    print(f"[ToolDiscovery] Error loading tool {tool_file}: {e}")
        
        # 2. Load MCP tools from memory_db
        try:
            lib_path = JARVIS_ROOT / 'lib'
            if str(lib_path) not in sys.path:
                sys.path.insert(0, str(lib_path))
            
            from memory_db import get_memory_db
            db = get_memory_db()
            
            # Get all tools from database
            all_db_tools = db.get_enabled_tool_names()
            
            for tool_name in all_db_tools:
                # Only add if not already loaded from local files
                if tool_name not in self.tools:
                    # Get tool details from db
                    tool_info = db.get_tool_info(tool_name) if hasattr(db, 'get_tool_info') else None
                    is_blocked = tool_name in blocked_tools
                    is_mcp = tool_name.startswith('mcp_')
                    
                    description = ''
                    if tool_info and isinstance(tool_info, dict):
                        description = tool_info.get('description', '')
                    
                    self.tools[tool_name] = {
                        'name': tool_name,
                        'description': description,
                        'enabled': not is_blocked,
                        'blocked': is_blocked,
                        'source': 'mcp' if is_mcp else 'database',
                        'parameters': {},
                        'script': None,
                        'file': None
                    }
        except Exception as e:
            print(f"[ToolDiscovery] Error loading MCP tools from db: {e}")
    
    def get_tools(self, include_blocked: bool = True) -> list[dict]:
        """Return all tools as a list"""
        if include_blocked:
            return list(self.tools.values())
        return [t for t in self.tools.values() if not t.get('blocked')]
    
    def get_tool(self, name: str) -> dict | None:
        """Get a specific tool by name"""
        return self.tools.get(name)
    
    def get_tool_count(self, include_blocked: bool = False) -> int:
        """Return count of tools"""
        if include_blocked:
            return len(self.tools)
        return len([t for t in self.tools.values() if not t.get('blocked')])
    
    def get_mcp_tools(self) -> list[dict]:
        """Return only MCP tools"""
        return [t for t in self.tools.values() if t.get('source') == 'mcp']
    
    def get_local_tools(self) -> list[dict]:
        """Return only local tools"""
        return [t for t in self.tools.values() if t.get('source') == 'local']
    
    def get_blocked_tools(self) -> list[dict]:
        """Return only blocked tools"""
        return [t for t in self.tools.values() if t.get('blocked')]
    
    def refresh(self):
        """Reload tools"""
        self._load_tools()
    
    def get_tools_summary(self) -> list[dict]:
        """Return simplified tool list for UI (full descriptions for sidebar tooltip)"""
        return [
            {
                'name': t['name'],
                'description': t['description'],
                'source': t.get('source', 'local'),
                'enabled': t.get('enabled', True),
                'blocked': t.get('blocked', False)
            }
            for t in sorted(self.tools.values(), key=lambda x: x['name'])
        ]
    
    def get_stats(self) -> dict:
        """Return tool statistics"""
        tools = list(self.tools.values())
        return {
            'total': len(tools),
            'local': len([t for t in tools if t.get('source') == 'local']),
            'mcp': len([t for t in tools if t.get('source') == 'mcp']),
            'enabled': len([t for t in tools if t.get('enabled')]),
            'blocked': len([t for t in tools if t.get('blocked')])
        }


# Singleton instance
_tool_service: ToolDiscoveryService | None = None


def get_tool_service() -> ToolDiscoveryService:
    """Get or create the tool discovery service singleton"""
    global _tool_service
    if _tool_service is None:
        _tool_service = ToolDiscoveryService()
    return _tool_service
