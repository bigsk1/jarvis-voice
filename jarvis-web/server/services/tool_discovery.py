"""
Tool Discovery Service
Auto-loads tools from skills/*.tool.json AND memory_db (includes MCP tools)
"""
import json
import sys
import threading
from pathlib import Path
from ..config import SKILLS_PATH, JARVIS_ROOT, get_web_setting


def _ensure_lib_path():
    lib_path = JARVIS_ROOT / "lib"
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))


def _tool_profile_overrides():
    """Load active profile overrides (same logic as ToolRegistry)."""
    _ensure_lib_path()
    from tool_profiles import load_active_profile_overrides

    return load_active_profile_overrides()


class ToolDiscoveryService:
    """Discovers and manages available Jarvis tools"""
    
    def __init__(self, skills_path: Path = None, mode: str = None):
        _ensure_lib_path()
        from config_loader import get_active_config_mode

        self.skills_path = skills_path or SKILLS_PATH
        self.mode = get_active_config_mode(mode)
        self.tools: dict[str, dict] = {}
        self._lock = threading.RLock()
        self.refresh()

    def _run_in_mode_scope(self):
        """Return a context manager for this service's immutable data mode."""
        _ensure_lib_path()
        from config_loader import config_scope

        return config_scope(self.mode)
    
    def _load_tools(self):
        """Load all tool definitions from skills folder AND memory_db"""
        self.tools = {}

        # Get blocked tools for web
        blocked_tools = set(get_web_setting('tools.blocked', []))

        profile_overrides = _tool_profile_overrides()
        _ensure_lib_path()
        from tool_availability import check_tool_availability
        from tool_profiles import effective_enabled

        # 1. Load local tools from skills/**/*.tool.json (including subdirectories like auto-tools/)
        if self.skills_path.exists():
            for tool_file in self.skills_path.glob('**/*.tool.json'):
                try:
                    with open(tool_file, 'r') as f:
                        tool = json.load(f)

                    name = tool.get('name', tool_file.stem.replace('.tool', ''))
                    is_blocked = name in blocked_tools
                    base_enabled = tool.get('enabled', True)
                    effective = effective_enabled(name, base_enabled, profile_overrides)

                    # Credential-aware availability (same evaluator as
                    # ToolRegistry). Unavailable tools MUST stay in this map
                    # (as enabled=False) so a stale enabled Tool RAG row can't
                    # resurrect them via the DB fallback in step 2 below.
                    availability = check_tool_availability(tool)

                    # Include all tools (effective enabled or blocked for visibility)
                    if effective or is_blocked:
                        self.tools[name] = {
                            'name': name,
                            'description': tool.get('description', ''),
                            'enabled': effective and not is_blocked and availability.available,
                            'blocked': is_blocked,
                            'available': availability.available,
                            'missing': list(availability.missing),
                            'setup_hint': availability.setup_hint,
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
                    # DB says enabled=1; still respect profile overrides (same as ToolRegistry)
                    if not effective_enabled(tool_name, True, profile_overrides):
                        continue
                    # Get the persisted Tool RAG definition without creating a
                    # second MCP connection just to populate Web UI metadata.
                    # Keep the legacy getter as a compatibility fallback for
                    # older/custom MemoryDB implementations.
                    tool_info = None
                    for getter_name in ('get_tool_definition', 'get_tool_info'):
                        getter = getattr(db, getter_name, None)
                        if not callable(getter):
                            continue
                        candidate = getter(tool_name)
                        if isinstance(candidate, dict):
                            tool_info = candidate
                            break
                    is_blocked = tool_name in blocked_tools
                    is_mcp = tool_name.startswith('mcp_')

                    description = ''
                    if tool_info and isinstance(tool_info, dict):
                        description = tool_info.get('description') or ''

                    self.tools[tool_name] = {
                        'name': tool_name,
                        'description': description,
                        'enabled': not is_blocked,
                        'blocked': is_blocked,
                        'available': True,
                        'missing': [],
                        'setup_hint': None,
                        'source': 'mcp' if is_mcp else 'database',
                        'parameters': {},
                        'script': None,
                        'file': None
                    }
        except Exception as e:
            print(f"[ToolDiscovery] Error loading MCP tools from db: {e}")
    
    def get_tools(self, include_blocked: bool = True) -> list[dict]:
        """Return all tools as a list"""
        with self._lock:
            if include_blocked:
                return list(self.tools.values())
            return [t for t in self.tools.values() if not t.get('blocked')]
    
    def get_tool(self, name: str) -> dict | None:
        """Get a specific tool by name"""
        with self._lock:
            return self.tools.get(name)
    
    def get_tool_count(self, include_blocked: bool = False) -> int:
        """Return count of CALLABLE tools.

        Excludes blocked tools (unless include_blocked) and tools whose
        credential requirements are unmet — those remain in the map for
        diagnostics/UI but are not callable, so counting them would overstate
        what the LLM can actually use.
        """
        with self._lock:
            if include_blocked:
                return len(self.tools)
            return len([
                t for t in self.tools.values()
                if not t.get('blocked') and t.get('available', True)
            ])
    
    def get_mcp_tools(self) -> list[dict]:
        """Return only MCP tools"""
        with self._lock:
            return [t for t in self.tools.values() if t.get('source') == 'mcp']
    
    def get_local_tools(self) -> list[dict]:
        """Return only local tools"""
        with self._lock:
            return [t for t in self.tools.values() if t.get('source') == 'local']
    
    def get_blocked_tools(self) -> list[dict]:
        """Return only blocked tools"""
        with self._lock:
            return [t for t in self.tools.values() if t.get('blocked')]
    
    def refresh(self):
        """Reload tools inside the service's own mode scope."""
        with self._lock, self._run_in_mode_scope():
            self._load_tools()
    
    def get_tools_summary(self) -> list[dict]:
        """Return simplified tool list for UI (full descriptions for sidebar tooltip)"""
        with self._lock:
            return [
                {
                    'name': t['name'],
                    'description': t['description'],
                    'source': t.get('source', 'local'),
                    'enabled': t.get('enabled', True),
                    'blocked': t.get('blocked', False),
                    'available': t.get('available', True),
                    'missing': t.get('missing', []),
                    'setup_hint': t.get('setup_hint')
                }
                for t in sorted(self.tools.values(), key=lambda x: x['name'])
            ]
    
    def get_stats(self) -> dict:
        """Return tool statistics"""
        with self._lock:
            tools = list(self.tools.values())
        return {
            'total': len(tools),
            'local': len([t for t in tools if t.get('source') == 'local']),
            'mcp': len([t for t in tools if t.get('source') == 'mcp']),
            'enabled': len([t for t in tools if t.get('enabled')]),
            'blocked': len([t for t in tools if t.get('blocked')]),
            'unavailable': len([t for t in tools if not t.get('available', True)])
        }


# One discovery snapshot per mode. A single process can serve concurrent cloud
# and local browser sessions, so a process-wide singleton would leak whichever
# profile was loaded most recently into the other mode's UI.
_tool_services: dict[str, ToolDiscoveryService] = {}
_tool_services_lock = threading.RLock()


def get_tool_service(mode: str = None) -> ToolDiscoveryService:
    """Get or create the discovery snapshot for one cloud/local mode."""
    _ensure_lib_path()
    from config_loader import get_active_config_mode

    resolved = get_active_config_mode(mode)
    with _tool_services_lock:
        service = _tool_services.get(resolved)
        if service is None:
            service = ToolDiscoveryService(mode=resolved)
            _tool_services[resolved] = service
        return service


def refresh_tool_services(mode: str = None) -> None:
    """Refresh one mode or every already-created discovery snapshot."""
    if mode is not None:
        get_tool_service(mode).refresh()
        return

    with _tool_services_lock:
        services = list(_tool_services.values())
    for service in services:
        service.refresh()


def reset_tool_services() -> None:
    """Drop cached discovery snapshots (primarily for tests and shutdown)."""
    with _tool_services_lock:
        _tool_services.clear()
