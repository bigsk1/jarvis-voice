#!/usr/bin/env python3
"""
Jarvis Voice Assistant - Workflow Loader

Loads workflow definitions from data/workflows/*.json plus optional
data/workflows/personal/*.json files, then matches incoming queries
against workflow triggers.

Workflows enable deterministic multi-tool execution (pipeline mode)
as an alternative to free-form LLM routing.
"""
import os
import sys
import json
from pathlib import Path

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))


class WorkflowLoader:
    """Load and match workflow definitions."""
    
    def __init__(self, workflows_dir: str = None, explicit_only: bool = True):
        """
        Initialize workflow loader.
        
        Args:
            workflows_dir: Path to workflows directory. 
                          Defaults to data/workflows/ relative to project root.
            explicit_only: If True (default), only match explicit commands like /research.
                          If False, also match patterns and keywords (risky - may hijack normal queries).
        """
        if workflows_dir:
            self.workflows_dir = Path(workflows_dir)
        else:
            project_root = Path(__file__).parent.parent.resolve()
            self.workflows_dir = project_root / "data" / "workflows"
        
        self.explicit_only = explicit_only
        self.workflows: dict[str, dict] = {}
        self._load_workflows()
    
    def _load_workflows(self):
        """Load all enabled workflow JSON files."""
        self.workflows = {}
        
        if not self.workflows_dir.exists():
            return
        
        for path in self._iter_workflow_files():
            try:
                with open(path, 'r') as f:
                    workflow = json.load(f)
                
                # Skip disabled workflows
                if not workflow.get("enabled", True):
                    continue
                
                # Validate required fields
                if not workflow.get("id"):
                    print(f"Warning: Workflow {path.name} missing 'id' field, skipping", 
                          file=sys.stderr)
                    continue
                
                if not workflow.get("steps"):
                    print(f"Warning: Workflow {workflow['id']} has no steps, skipping",
                          file=sys.stderr)
                    continue
                
                # Store workflow
                self.workflows[workflow["id"]] = workflow
                
            except json.JSONDecodeError as e:
                print(f"Warning: Invalid JSON in {path.name}: {e}", file=sys.stderr)
            except Exception as e:
                print(f"Warning: Error loading {path.name}: {e}", file=sys.stderr)

    def _iter_workflow_files(self):
        """Yield shared workflow files, then personal overrides."""
        yield from sorted(self.workflows_dir.glob("*.json"))

        personal_dir = self.workflows_dir / "personal"
        if personal_dir.exists():
            yield from sorted(personal_dir.glob("*.json"))
    
    def match(self, query: str, allow_patterns: bool = None) -> dict | None:
        """
        Match query against workflow triggers.
        
        By default (explicit_only=True), ONLY matches explicit commands like /research.
        This prevents workflows from accidentally hijacking normal queries.
        
        Matching priority (when patterns allowed):
        1. Explicit commands (e.g., "/research") - ALWAYS checked
        2. Patterns (e.g., "research about") - Only if explicit_only=False
        3. Keywords (all must match) - Only if explicit_only=False
        
        Args:
            query: User's input query
            allow_patterns: Override explicit_only setting for this call.
                           None = use instance setting.
            
        Returns:
            Matching workflow dict, or None if no match
        """
        if not query:
            return None
        
        query_lower = query.lower().strip()
        
        # Determine if we should check patterns/keywords
        check_patterns = not (self.explicit_only if allow_patterns is None else not allow_patterns)
        
        # Score each workflow and pick best match
        best_match = None
        best_score = 0
        
        for workflow in self.workflows.values():
            score = self._score_match(query_lower, workflow, check_patterns)
            if score > best_score:
                best_score = score
                best_match = workflow
        
        # Require minimum score to match
        # 100+ = explicit command (always allowed, score = 100 + command length)
        # 50 = pattern match (only if patterns allowed)
        # 30 = keyword match (only if patterns allowed)
        if best_score >= 100:  # Explicit command (100 + length)
            return best_match
        elif best_score >= 10 and check_patterns:  # Pattern/keyword match
            return best_match
        
        return None
    
    def _score_match(self, query_lower: str, workflow: dict, check_patterns: bool = True) -> int:
        """
        Score how well a query matches a workflow's triggers.
        
        Scoring:
        - Explicit command match: 100 + len(command) points (longer = better match)
        - Pattern match: 50 points (only if check_patterns=True)
        - All keywords match: 30 points (only if check_patterns=True)
        - Partial keywords: 10 points per keyword (only if check_patterns=True)
        
        Args:
            query_lower: Lowercase query string
            workflow: Workflow definition dict
            check_patterns: Whether to check patterns/keywords (False = explicit only)
            
        Returns:
            Match score (0 = no match)
        """
        triggers = workflow.get("triggers", {})
        score = 0
        
        # 1. Check explicit commands (ALWAYS checked, highest priority)
        # Score by length so longer/more specific commands win
        # e.g., /status-visual (14 chars) beats /status (7 chars)
        for explicit in triggers.get("explicit", []):
            explicit_lower = explicit.lower()
            if query_lower.startswith(explicit_lower):
                # Add length to base score so longer matches win
                match_score = 100 + len(explicit_lower)
                score = max(score, match_score)
        
        # If explicit match found or explicit_only mode, return now
        if score >= 100 or not check_patterns:
            return score
        
        # 2. Check patterns (only if patterns allowed)
        for pattern in triggers.get("patterns", []):
            if pattern.lower() in query_lower:
                score = max(score, 50)
        
        # 3. Check keywords (only if patterns allowed)
        keywords = triggers.get("keywords", [])
        if keywords:
            matched_keywords = sum(
                1 for kw in keywords 
                if kw.lower() in query_lower
            )
            
            if matched_keywords == len(keywords):
                # All keywords match
                score = max(score, 30)
            elif matched_keywords > 0:
                # Partial keyword match
                score = max(score, matched_keywords * 10)
        
        return score
    
    def get_workflow(self, workflow_id: str) -> dict | None:
        """
        Get a workflow by ID.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            Workflow dict or None
        """
        return self.workflows.get(workflow_id)
    
    def list_workflows(self) -> list[dict]:
        """
        List all enabled workflows.
        
        Returns:
            List of workflow dicts with basic info
        """
        return [
            {
                "id": w["id"],
                "name": w.get("name", w["id"]),
                "description": w.get("description", ""),
                "triggers": w.get("triggers", {}),
                "step_count": len(w.get("steps", []))
            }
            for w in self.workflows.values()
        ]
    
    def reload(self):
        """Hot-reload workflows (for development)."""
        self._load_workflows()
    
    def validate_workflow(self, workflow: dict) -> list[str]:
        """
        Validate a workflow definition.
        
        Args:
            workflow: Workflow dict to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        # Required fields
        if not workflow.get("id"):
            errors.append("Missing required field: id")
        
        if not workflow.get("steps"):
            errors.append("Missing required field: steps")
        elif not isinstance(workflow["steps"], list):
            errors.append("Field 'steps' must be a list")
        else:
            # Validate each step
            for i, step in enumerate(workflow["steps"]):
                step_num = step.get("step", i + 1)
                
                if not step.get("tool"):
                    errors.append(f"Step {step_num}: Missing required field 'tool'")
        
        # Validate triggers if present
        triggers = workflow.get("triggers", {})
        if triggers:
            if not any([
                triggers.get("explicit"),
                triggers.get("patterns"),
                triggers.get("keywords")
            ]):
                errors.append("Triggers defined but no explicit/patterns/keywords specified")
        
        return errors


def main():
    """CLI for testing workflow loader."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Workflow Loader CLI")
    parser.add_argument("action", choices=["list", "match", "validate"],
                       help="Action to perform")
    parser.add_argument("--query", "-q", help="Query to match against workflows")
    parser.add_argument("--workflow", "-w", help="Workflow ID to validate")
    parser.add_argument("--dir", "-d", help="Workflows directory path")
    parser.add_argument("--allow-patterns", "-p", action="store_true",
                       help="Also match patterns/keywords (default: explicit commands only)")
    
    args = parser.parse_args()
    
    # Default: explicit_only=True (safe mode)
    loader = WorkflowLoader(args.dir, explicit_only=not args.allow_patterns)
    
    if args.action == "list":
        workflows = loader.list_workflows()
        if not workflows:
            print("No workflows loaded")
        else:
            print(f"Loaded {len(workflows)} workflow(s):\n")
            for w in workflows:
                print(f"  {w['id']}")
                print(f"    Name: {w['name']}")
                print(f"    Steps: {w['step_count']}")
                print(f"    Triggers: {w['triggers']}")
                print()
    
    elif args.action == "match":
        if not args.query:
            print("Error: --query required for match action")
            sys.exit(1)
        
        workflow = loader.match(args.query)
        if workflow:
            print(f"Matched workflow: {workflow['id']}")
            print(f"  Name: {workflow.get('name', workflow['id'])}")
            print(f"  Steps: {len(workflow.get('steps', []))}")
        else:
            print("No workflow matched")
    
    elif args.action == "validate":
        if not args.workflow:
            # Validate all workflows
            for wf in loader.workflows.values():
                errors = loader.validate_workflow(wf)
                if errors:
                    print(f"Workflow {wf['id']}: INVALID")
                    for err in errors:
                        print(f"  - {err}")
                else:
                    print(f"Workflow {wf['id']}: OK")
        else:
            workflow = loader.get_workflow(args.workflow)
            if not workflow:
                print(f"Workflow '{args.workflow}' not found")
                sys.exit(1)
            
            errors = loader.validate_workflow(workflow)
            if errors:
                print(f"Workflow {args.workflow}: INVALID")
                for err in errors:
                    print(f"  - {err}")
                sys.exit(1)
            else:
                print(f"Workflow {args.workflow}: OK")


if __name__ == "__main__":
    main()
