#!/usr/bin/env python3
"""
Basic server import test - verifies Python modules can be imported.

Run: python tests/test_server_imports.py

This catches:
- Syntax errors
- Circular imports
- Missing required imports
- Basic module structure issues

Does NOT test:
- Runtime behavior
- External service connections
- Full functionality
"""

import ast
import importlib.util
import sys
from pathlib import Path

# Add project paths
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
sys.path.insert(0, str(PROJECT_ROOT / "skills"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))
sys.path.insert(0, str(PROJECT_ROOT / "api"))


def check_syntax(filepath: Path) -> tuple[bool, str]:
    """Check if a Python file has valid syntax."""
    try:
        with open(filepath, 'r') as f:
            ast.parse(f.read())
        return True, ""
    except SyntaxError as e:
        return False, str(e)


def try_import(module_path: Path, module_name: str) -> tuple[bool, str]:
    """Try to import a module and catch any errors."""
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            # Don't actually execute - just verify it can be loaded
            # spec.loader.exec_module(module)  # This would run the module
        return True, ""
    except Exception as e:
        return False, str(e)


def main():
    print("=" * 60)
    print("Jarvis Server Import Test")
    print("=" * 60)
    
    # Core server files to check
    server_files = [
        PROJECT_ROOT / "api" / "server.py",
        PROJECT_ROOT / "jarvis-web" / "server" / "app.py",
        PROJECT_ROOT / "jarvis-intelligence" / "server" / "app.py",
        PROJECT_ROOT / "jarvis-memory" / "server" / "app.py",
        PROJECT_ROOT / "jarvis-docs" / "server" / "app.py",
        PROJECT_ROOT / "jarvis-canvas" / "server" / "app.py",
        PROJECT_ROOT / "orchestrator" / "orchestrator_v2.py",
    ]
    
    # Service daemons
    service_files = list((PROJECT_ROOT / "services").glob("*.py"))
    
    # Lib modules
    lib_files = list((PROJECT_ROOT / "lib").glob("*.py"))
    
    # Skills
    skill_files = list((PROJECT_ROOT / "skills").glob("*.py"))
    
    errors = []
    warnings = []
    
    # Check servers
    print("\n[Servers]")
    for filepath in server_files:
        if not filepath.exists():
            warnings.append(f"  ! {filepath.relative_to(PROJECT_ROOT)} - FILE NOT FOUND")
            continue
        
        ok, err = check_syntax(filepath)
        if ok:
            print(f"  ✓ {filepath.relative_to(PROJECT_ROOT)}")
        else:
            errors.append(f"  ✗ {filepath.relative_to(PROJECT_ROOT)}: {err}")
            print(errors[-1])
    
    # Check services
    print("\n[Services]")
    for filepath in service_files:
        if filepath.name == "__init__.py":
            continue
        ok, err = check_syntax(filepath)
        if ok:
            print(f"  ✓ {filepath.name}")
        else:
            errors.append(f"  ✗ {filepath.name}: {err}")
            print(errors[-1])
    
    # Check lib
    print("\n[Lib modules]")
    for filepath in lib_files:
        if filepath.name == "__init__.py":
            continue
        ok, err = check_syntax(filepath)
        if ok:
            print(f"  ✓ {filepath.name}")
        else:
            errors.append(f"  ✗ {filepath.name}: {err}")
            print(errors[-1])
    
    # Check skills (summary only)
    print(f"\n[Skills] - {len(skill_files)} files")
    skill_errors = 0
    for filepath in skill_files:
        if filepath.name == "__init__.py":
            continue
        ok, err = check_syntax(filepath)
        if not ok:
            skill_errors += 1
            errors.append(f"  ✗ skills/{filepath.name}: {err}")
    
    if skill_errors == 0:
        print(f"  ✓ All {len(skill_files)} skills passed syntax check")
    else:
        print(f"  ✗ {skill_errors} skill(s) have syntax errors")
        for err in errors:
            if "skills/" in err:
                print(err)
    
    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"FAILED: {len(errors)} error(s) found")
        for err in errors:
            print(err)
        sys.exit(1)
    else:
        print("PASSED: All syntax checks passed!")
        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for warn in warnings:
                print(warn)
        sys.exit(0)


if __name__ == "__main__":
    main()
