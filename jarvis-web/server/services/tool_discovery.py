"""
Tool Discovery Service
Auto-loads tools from skills/*.tool.json
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from ..config import SKILLS_PATH


class ToolDiscoveryService:
    """Discovers and manages available Jarvis tools"""
    
    def __init__(self, skills_path: Path = None):
        self.skills_path = skills_path or SKILLS_PATH
        self.tools: Dict[str, dict] = {}
        self._load_tools()
    
    def _load_tools(self):
        """Load all tool definitions from skills folder"""
        self.tools = {}
        
        if not self.skills_path.exists():
            print(f"Warning: Skills path does not exist: {self.skills_path}")
            return
        
        for tool_file in self.skills_path.glob('*.tool.json'):
            try:
                with open(tool_file, 'r') as f:
                    tool = json.load(f)
                    
                # Only include enabled tools
                if tool.get('enabled', True):
                    name = tool.get('name', tool_file.stem.replace('.tool', ''))
                    self.tools[name] = {
                        'name': name,
                        'description': tool.get('description', ''),
                        'enabled': True,
                        'parameters': tool.get('parameters', {}),
                        'script': tool.get('script', ''),
                        'file': str(tool_file)
                    }
            except Exception as e:
                print(f"Error loading tool {tool_file}: {e}")
    
    def get_tools(self) -> List[dict]:
        """Return all enabled tools as a list"""
        return list(self.tools.values())
    
    def get_tool(self, name: str) -> Optional[dict]:
        """Get a specific tool by name"""
        return self.tools.get(name)
    
    def get_tool_count(self) -> int:
        """Return count of enabled tools"""
        return len(self.tools)
    
    def refresh(self):
        """Reload tools from disk"""
        self._load_tools()
    
    def get_tools_summary(self) -> List[dict]:
        """Return simplified tool list for UI"""
        return [
            {
                'name': t['name'],
                'description': t['description'][:100] + '...' if len(t['description']) > 100 else t['description']
            }
            for t in self.tools.values()
        ]


# Singleton instance
_tool_service: Optional[ToolDiscoveryService] = None


def get_tool_service() -> ToolDiscoveryService:
    """Get or create the tool discovery service singleton"""
    global _tool_service
    if _tool_service is None:
        _tool_service = ToolDiscoveryService()
    return _tool_service

