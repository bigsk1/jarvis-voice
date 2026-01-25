#!/usr/bin/env python3
"""
Tool Management Utility
Enable/disable tools and view tool status.
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


def list_tools(verbose: bool = False) -> None:
    """List all tools and their enabled status."""
    skills_dir = get_skills_dir()
    tools = []
    
    for tool_file in sorted(skills_dir.glob("*.tool.json")):
        try:
            with open(tool_file, 'r') as f:
                config = json.load(f)
            
            enabled = config.get('enabled', True)  # Default to True for backward compatibility
            status = f"{GREEN}✓ enabled{RESET}" if enabled else f"{RED}⊝ disabled{RESET}"
            
            tools.append({
                'name': config.get('name', tool_file.stem),
                'enabled': enabled,
                'file': tool_file.name,
                'description': config.get('description', 'No description')[:60]
            })
            
            if verbose:
                print(f"{status:20} {tools[-1]['name']:25} {tools[-1]['description']}")
            else:
                print(f"{status:20} {tools[-1]['name']}")
        except Exception as e:
            print(f"{RED}✗ Error loading {tool_file.name}: {e}{RESET}")
    
    # Summary
    enabled_count = sum(1 for t in tools if t['enabled'])
    disabled_count = len(tools) - enabled_count
    print(f"\n{BLUE}Total: {len(tools)} tools ({enabled_count} enabled, {disabled_count} disabled){RESET}")


def enable_tool(tool_name: str) -> None:
    """Enable a tool."""
    skills_dir = get_skills_dir()
    tool_file = skills_dir / f"{tool_name}.tool.json"
    
    if not tool_file.exists():
        print(f"{RED}✗ Tool not found: {tool_name}{RESET}")
        print(f"  Looking for: {tool_file}")
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
    tool_file = skills_dir / f"{tool_name}.tool.json"
    
    if not tool_file.exists():
        print(f"{RED}✗ Tool not found: {tool_name}{RESET}")
        print(f"  Looking for: {tool_file}")
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
    
    for tool_file in skills_dir.glob("*.tool.json"):
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
    
    for tool_file in skills_dir.glob("*.tool.json"):
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


def main():
    parser = argparse.ArgumentParser(
        description='Manage Jarvis tools (enable/disable)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all tools
  ./bin/manage-tools.py list
  
  # List with descriptions
  ./bin/manage-tools.py list -v
  
  # Disable a tool
  ./bin/manage-tools.py disable execute_bash
  
  # Enable a tool
  ./bin/manage-tools.py enable execute_bash
  
  # Enable all tools
  ./bin/manage-tools.py enable-all
  
  # Add 'enabled' field to all tools (migration)
  ./bin/manage-tools.py init
        """
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


if __name__ == '__main__':
    main()

