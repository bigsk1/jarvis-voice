#!/usr/bin/env python3
"""
Manage Jarvis tool definitions (skills/**/*.tool.json) and inspect profile overlays.

Profile overlays (optional): set JARVIS_TOOL_PROFILE in config/local.env or cloud.env
to the stem of skills/profiles/<name>.json. Only skills/profiles/default.json is tracked
in git; add other JSON files locally. After changing a profile, restart services and run
./bin/sync-tools.py local (or cloud). See skills/README.md (Tool profiles).

Usage (run with -h / --help on this script or on a subcommand for full flags):

  ./bin/manage-tools.py -h
      Top-level help and command list.

  ./bin/manage-tools.py list
  ./bin/manage-tools.py list -v
  ./bin/manage-tools.py list --verbose
      List all tools with effective enabled/disabled (merges .tool.json + active profile).

  ./bin/manage-tools.py enable <tool_name>
  ./bin/manage-tools.py disable <tool_name>
      Set "enabled" in the tool file (resolves name in skills/ and skills/auto-tools/).

  ./bin/manage-tools.py enable-all
      Set enabled true on every tool file (root + auto-tools).

  ./bin/manage-tools.py init
      Add missing "enabled": true to tool JSON (migration helper).

  ./bin/manage-tools.py profile -h
  ./bin/manage-tools.py profile list
  ./bin/manage-tools.py profile show
  ./bin/manage-tools.py profile export
  ./bin/manage-tools.py profile export > /tmp/tool-state.json
      Profile list/show/export (export: JSON of base vs effective enabled per tool).

Environment:
  JARVIS_TOOL_PROFILE       Active profile stem (default: default).
  JARVIS_OVERRIDE_*         Web UI overrides for config keys (see lib/config_loader.py).
"""

_EXAMPLES = """
Examples:
  ./bin/manage-tools.py list
  ./bin/manage-tools.py list -v
  ./bin/manage-tools.py disable weather
  ./bin/manage-tools.py enable weather
  ./bin/manage-tools.py enable-all
  ./bin/manage-tools.py init
  ./bin/manage-tools.py profile list
  ./bin/manage-tools.py profile show
  ./bin/manage-tools.py profile export > /tmp/tool-state.json
"""

import sys
import json
import argparse
from pathlib import Path

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def get_skills_dir() -> Path:
    """Get skills directory path."""
    return Path(__file__).parent.parent / "skills"


def get_project_root() -> Path:
    return Path(__file__).parent.parent


def _ensure_lib_path():
    lib = get_project_root() / "lib"
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))


def iter_tool_files(skills_dir: Path):
    """All *.tool.json under skills/ and skills/auto-tools/."""
    yield from sorted(skills_dir.glob("*.tool.json"))
    auto = skills_dir / "auto-tools"
    if auto.is_dir():
        yield from sorted(auto.glob("*.tool.json"))


def list_tools(verbose: bool = False) -> None:
    """List all tools and their enabled status."""
    skills_dir = get_skills_dir()
    tools = []
    _ensure_lib_path()
    from tool_profiles import effective_enabled, get_active_profile_name, load_active_profile_overrides

    profile_name = get_active_profile_name()
    overrides = load_active_profile_overrides()

    for tool_file in iter_tool_files(skills_dir):
        try:
            with open(tool_file, 'r') as f:
                config = json.load(f)
            
            base_enabled = config.get('enabled', True)  # Default to True for backward compatibility
            name = config.get('name', tool_file.stem)
            eff = effective_enabled(name, base_enabled, overrides)
            status = f"{GREEN}✓ enabled{RESET}" if eff else f"{RED}⊝ disabled{RESET}"
            tools.append({
                'name': name,
                'enabled': eff,
                'base_enabled': base_enabled,
                'file': tool_file.name,
                'description': config.get('description', 'No description')[:60]
            })

            if verbose:
                extra = ""
                if name in overrides and base_enabled != eff:
                    extra = f" {YELLOW}(profile {profile_name}){RESET}"
                print(f"{status:20} {tools[-1]['name']:25} {tools[-1]['description']}{extra}")
            else:
                print(f"{status:20} {tools[-1]['name']}")
        except Exception as e:
            print(f"{RED}✗ Error loading {tool_file.name}: {e}{RESET}")
    
    # Summary
    enabled_count = sum(1 for t in tools if t['enabled'])
    disabled_count = len(tools) - enabled_count
    print(
        f"\n{BLUE}Total: {len(tools)} tools ({enabled_count} enabled, {disabled_count} disabled) — "
        f"profile: {profile_name}{RESET}"
    )


def resolve_tool_file(skills_dir: Path, tool_name: str) -> Path | None:
    """Find skills/**/<name>.tool.json by JSON ``name`` field (includes auto-tools/)."""
    for tool_file in iter_tool_files(skills_dir):
        try:
            with open(tool_file, 'r') as f:
                config = json.load(f)
            if config.get('name', tool_file.stem) == tool_name:
                return tool_file
        except Exception:
            continue
    return None


def enable_tool(tool_name: str) -> None:
    """Enable a tool."""
    skills_dir = get_skills_dir()
    tool_file = resolve_tool_file(skills_dir, tool_name)
    if tool_file is None:
        alt = skills_dir / f"{tool_name}.tool.json"
        print(f"{RED}✗ Tool not found: {tool_name}{RESET}")
        print(f"  Tried resolve by name and: {alt}")
        return
    
    try:
        with open(tool_file, 'r') as f:
            config = json.load(f)
        
        config['enabled'] = True
        
        with open(tool_file, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')
        
        print(f"{GREEN}✓ Enabled tool: {tool_name}{RESET}")
    except Exception as e:
        print(f"{RED}✗ Failed to enable {tool_name}: {e}{RESET}")


def disable_tool(tool_name: str) -> None:
    """Disable a tool."""
    skills_dir = get_skills_dir()
    tool_file = resolve_tool_file(skills_dir, tool_name)
    if tool_file is None:
        alt = skills_dir / f"{tool_name}.tool.json"
        print(f"{RED}✗ Tool not found: {tool_name}{RESET}")
        print(f"  Tried resolve by name and: {alt}")
        return
    
    try:
        with open(tool_file, 'r') as f:
            config = json.load(f)
        
        config['enabled'] = False
        
        with open(tool_file, 'w') as f:
            json.dump(config, f, indent=2)
            f.write('\n')
        
        print(f"{YELLOW}⊝ Disabled tool: {tool_name}{RESET}")
    except Exception as e:
        print(f"{RED}✗ Failed to disable {tool_name}: {e}{RESET}")


def enable_all_tools() -> None:
    """Enable all tools."""
    skills_dir = get_skills_dir()
    count = 0

    for tool_file in iter_tool_files(skills_dir):
        try:
            with open(tool_file, 'r') as f:
                config = json.load(f)
            
            if not config.get('enabled', True):
                config['enabled'] = True
                with open(tool_file, 'w') as f:
                    json.dump(config, f, indent=2)
                    f.write('\n')
                count += 1
        except Exception as e:
            print(f"{RED}✗ Error processing {tool_file.name}: {e}{RESET}")
    
    print(f"{GREEN}✓ Enabled {count} tool(s){RESET}")


def add_enabled_field() -> None:
    """Add 'enabled': true to all tools that don't have it."""
    skills_dir = get_skills_dir()
    count = 0

    for tool_file in iter_tool_files(skills_dir):
        try:
            with open(tool_file, 'r') as f:
                config = json.load(f)
            
            if 'enabled' not in config:
                config['enabled'] = True
                
                # Preserve order: enabled should go near the top
                ordered_config = {'enabled': config.pop('enabled')}
                ordered_config.update(config)
                
                with open(tool_file, 'w') as f:
                    json.dump(ordered_config, f, indent=2)
                    f.write('\n')
                
                print(f"{GREEN}✓ Added 'enabled' field to {config.get('name', tool_file.stem)}{RESET}")
                count += 1
        except Exception as e:
            print(f"{RED}✗ Error processing {tool_file.name}: {e}{RESET}")
    
    if count == 0:
        print(f"{BLUE}All tools already have 'enabled' field{RESET}")
    else:
        print(f"\n{GREEN}✓ Updated {count} tool(s){RESET}")


def cmd_profile_list() -> None:
    """List JSON profiles under skills/profiles/."""
    _ensure_lib_path()
    from tool_profiles import get_active_profile_name, get_profiles_dir, list_profile_names

    d = get_profiles_dir()
    names = list_profile_names()
    active = get_active_profile_name()
    if not names:
        print(f"{YELLOW}No profiles found under {d}{RESET}")
        print("  Add skills/profiles/<name>.json (see skills/README.md, Tool profiles)")
        return
    for n in names:
        mark = f" {GREEN}(active){RESET}" if n == active else ""
        print(f"  {n}{mark}")


def cmd_profile_show() -> None:
    """Show active profile and override count."""
    _ensure_lib_path()
    from tool_profiles import (
        describe_active_profile,
        get_active_profile_name,
        get_profiles_dir,
        load_active_profile_overrides,
    )

    name = get_active_profile_name()
    path = get_profiles_dir() / f"{name}.json"
    ov = load_active_profile_overrides()
    print(describe_active_profile(verbose=True))
    print(f"  File: {path} ({'exists' if path.is_file() else 'missing — empty overrides'})")
    if ov:
        for k in sorted(ov.keys()):
            state = 'on' if ov[k] else 'off'
            print(f"    {k}: {state}")


def cmd_profile_export() -> None:
    """Print effective enabled map (base from .tool.json merged with profile) as JSON."""
    _ensure_lib_path()
    from tool_profiles import effective_enabled, get_active_profile_name, load_active_profile_overrides

    skills_dir = get_skills_dir()
    overrides = load_active_profile_overrides()
    profile = get_active_profile_name()
    out: dict[str, dict] = {"profile": profile, "tools": {}}
    for tool_file in iter_tool_files(skills_dir):
        try:
            with open(tool_file, 'r') as f:
                config = json.load(f)
            name = config.get('name', tool_file.stem)
            base = config.get('enabled', True)
            out["tools"][name] = {
                "file": str(tool_file.relative_to(get_project_root())),
                "base_enabled": base,
                "effective_enabled": effective_enabled(name, base, overrides),
            }
        except Exception as e:
            out["tools"][tool_file.name] = {"error": str(e)}
    print(json.dumps(out, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description='Manage Jarvis tools (enable/disable) and profile overlays.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EXAMPLES
        + "\nSee the module docstring at the top of this file for full usage and environment notes.\n",
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all tools')
    list_parser.add_argument('-v', '--verbose', action='store_true', help='Show descriptions')
    
    # Enable command
    enable_parser = subparsers.add_parser('enable', help='Enable a tool')
    enable_parser.add_argument('tool_name', help='Tool name (e.g., execute_bash)')
    
    # Disable command
    disable_parser = subparsers.add_parser('disable', help='Disable a tool')
    disable_parser.add_argument('tool_name', help='Tool name (e.g., execute_bash)')
    
    # Enable all command
    subparsers.add_parser('enable-all', help='Enable all tools')
    
    # Init command (add enabled field)
    subparsers.add_parser('init', help='Add enabled field to all tools')

    prof = subparsers.add_parser('profile', help='Tool profile overlays (skills/profiles/*.json)')
    prof_sub = prof.add_subparsers(dest='profile_cmd', help='Profile command')
    prof_sub.add_parser('list', help='List profile files and mark active (JARVIS_TOOL_PROFILE)')
    prof_sub.add_parser('show', help='Show active profile and overrides')
    prof_sub.add_parser('export', help='Export effective enabled state as JSON (stdout)')

    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    if args.command == 'list':
        list_tools(args.verbose)
    elif args.command == 'enable':
        enable_tool(args.tool_name)
    elif args.command == 'disable':
        disable_tool(args.tool_name)
    elif args.command == 'enable-all':
        enable_all_tools()
    elif args.command == 'init':
        add_enabled_field()
    elif args.command == 'profile':
        if not getattr(args, 'profile_cmd', None):
            prof.print_help()
            sys.exit(1)
        pc = args.profile_cmd
        if pc == 'list':
            cmd_profile_list()
        elif pc == 'show':
            cmd_profile_show()
        elif pc == 'export':
            cmd_profile_export()


if __name__ == '__main__':
    main()

