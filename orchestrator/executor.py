#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Orchestrator Executor
Executes tools/skills and formats responses for TTS.
"""
import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from config_loader import load_config


class ToolExecutor:
    """Executes tools and skills."""
    
    def __init__(self, mode='cloud'):
        """Initialize executor."""
        self.mode = mode
        load_config(mode)
        self.project_root = Path(__file__).parent.parent.resolve()
        self.skills_dir = self.project_root / "skills"
    
    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool/skill.
        
        Args:
            tool_name: Name of the tool to execute
            args: Arguments to pass to the tool
            
        Returns:
            dict: Tool result
            {
                "ok": True/False,
                "speech": "Text to speak",
                "data": {...} (optional)
            }
        """
        # Check if tool exists
        tool_script = self.skills_dir / f"{tool_name}.sh"
        if not tool_script.exists():
            tool_script = self.skills_dir / f"{tool_name}.py"
        
        if not tool_script.exists():
            return {
                "ok": False,
                "speech": f"Tool {tool_name} not found",
                "error": "Tool not found"
            }
        
        # Execute tool
        try:
            input_json = json.dumps(args)
            result = subprocess.run(
                [str(tool_script)],
                input=input_json,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.skills_dir
            )
            
            if result.returncode != 0:
                return {
                    "ok": False,
                    "speech": f"Tool {tool_name} failed",
                    "error": result.stderr
                }
            
            # Parse output
            output = json.loads(result.stdout)
            return output
            
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "speech": f"Tool {tool_name} timed out",
                "error": "Timeout"
            }
        except json.JSONDecodeError as e:
            return {
                "ok": False,
                "speech": f"Tool {tool_name} returned invalid JSON",
                "error": str(e)
            }
        except Exception as e:
            return {
                "ok": False,
                "speech": f"Error executing {tool_name}",
                "error": str(e)
            }


def main():
    """CLI interface for testing."""
    if len(sys.argv) < 3:
        print("Usage: executor.py <mode> <tool_name> [args_json]", file=sys.stderr)
        sys.exit(1)
    
    mode = sys.argv[1]
    tool_name = sys.argv[2]
    args = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    
    executor = ToolExecutor(mode)
    result = executor.execute(tool_name, args)
    
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

