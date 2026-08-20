#!/usr/bin/env python3
"""
GitHub Release Notes Analyzer

Given a GitHub release URL or repo URL, fetch release data and produce a concise,
actionable summary with optional deep context from commits, PRs, and issues.

Outputs:
- Short speech summary
- Structured JSON for follow-up actions
- Markdown report saved to stash
- Optional Canvas page
"""

import base64
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from config_loader import load_config, get_config_value
from http_client import (
    get_proxy_chain,
    proxy_policy_allows_direct_fallback,
    proxy_response_indicates_tunnel_failure,
)
from stash_helper import open_space, StashFile
from memory_db import MemoryDB


API_BASE = "https://api.github.com"
API_VERSION = "2022-11-28"


@dataclass
class RepoTarget:
    owner: str
    repo: str
    tag: str | None = None


def now_iso() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def sanitize_name(value: str, fallback: str = "release_notes") -> str:
    clean = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", (value or "").strip())
    clean = re.sub(r"\s+", "_", clean)
    return clean[:140] if clean else fallback


def parse_repo_target(target: str, explicit_tag: str | None = None) -> RepoTarget:
    """
    Supports:
    - https://github.com/owner/repo
    - https://github.com/owner/repo/releases/tag/vX.Y.Z
    - owner/repo
    """
    target = (target or "").strip()
    if not target:
        raise ValueError("target is required")

    # owner/repo shorthand
    shorthand = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$", target)
    if shorthand:
        owner, repo = shorthand.group(1), shorthand.group(2).replace(".git", "")
        return RepoTarget(owner=owner, repo=repo, tag=explicit_tag)

    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != "github.com":
        raise ValueError("target must be a github.com repo URL, release URL, or owner/repo")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("invalid GitHub URL: expected /owner/repo")

    owner = parts[0]
    repo = parts[1].replace(".git", "")
    tag = explicit_tag

    # Release tag URL: /owner/repo/releases/tag/<tag>
    if len(parts) >= 5 and parts[2] == "releases" and parts[3] == "tag":
        tag = parts[4]

    return RepoTarget(owner=owner, repo=repo, tag=tag)


def extract_issue_or_pr_numbers(text: str) -> set[int]:
    """Extract #123 style references (basic heuristic)."""
    if not text:
        return set()
    return {int(x) for x in re.findall(r"(?<![A-Za-z0-9_/])#(\d+)\b", text)}


def summarize_commit_type(message: str) -> str:
    """
    Classify commit by conventional commit prefix if present.
    Returns: feat|fix|perf|refactor|docs|chore|ci|test|other
    """
    if not message:
        return "other"
    first = message.splitlines()[0].strip().lower()
    m = re.match(r"^(feat|fix|perf|refactor|docs|chore|ci|test)(\(.+\))?!?:", first)
    if m:
        return m.group(1)
    return "other"


def detect_breaking_changes(release_body: str, commits: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    if release_body:
        for line in release_body.splitlines():
            if "breaking" in line.lower():
                items.append(line.strip())
    for c in commits:
        msg = (c.get("commit") or {}).get("message", "")
        first = msg.splitlines()[0] if msg else ""
        if "BREAKING CHANGE" in msg or re.search(r"^[a-z]+(\(.+\))?!:", first, re.IGNORECASE):
            items.append(first.strip())
    # de-duplicate, keep order
    seen = set()
    unique = []
    for i in items:
        if i and i not in seen:
            seen.add(i)
            unique.append(i)
    return unique[:20]


class GitHubClient:
    def __init__(self):
        token = (
            get_config_value("GITHUB_TOKEN")
            or os.getenv("GITHUB_TOKEN")
            or os.getenv("GH_TOKEN")
            or ""
        ).strip()

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "jarvis-git-release-notes/1.0",
        })
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path: str, params: dict | None = None, timeout: int = 30) -> tuple[int, Any]:
        url = f"{API_BASE}{path}"
        chain = get_proxy_chain()
        last_err: requests.exceptions.RequestException | None = None

        for proxies in chain:
            try:
                resp = self.session.get(url, params=params, timeout=timeout, proxies=proxies)
                if proxy_response_indicates_tunnel_failure(resp):
                    resp.close()
                    continue
                return self._parse_github_response(resp)
            except requests.RequestException as e:
                last_err = e
                continue

        if not proxy_policy_allows_direct_fallback(default=True):
            if last_err:
                raise last_err
            raise requests.exceptions.ProxyError(
                "proxy_policy=require but no configured proxy completed the request"
            )

        try:
            resp = self.session.get(url, params=params, timeout=timeout, proxies=None)
            return self._parse_github_response(resp)
        except requests.RequestException:
            if last_err:
                raise last_err
            raise

    @staticmethod
    def _parse_github_response(resp: requests.Response) -> tuple[int, Any]:
        if resp.status_code == 204:
            return resp.status_code, {}
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"raw": resp.text}


def fetch_release_context(
    gh: GitHubClient,
    target: RepoTarget,
    mode: str,
    max_commits: int,
    max_prs: int,
    max_issues: int,
    include_prs: bool,
    include_issues: bool,
) -> dict[str, Any]:
    owner, repo = target.owner, target.repo

    # Repo metadata
    repo_status, repo_data = gh.get(f"/repos/{owner}/{repo}")
    if repo_status != 200:
        msg = repo_data.get("message", "unknown error") if isinstance(repo_data, dict) else "unknown error"
        raise ValueError(f"GitHub repo lookup failed: {msg}")

    # Resolve release
    release = None
    if target.tag:
        code, data = gh.get(f"/repos/{owner}/{repo}/releases/tags/{target.tag}")
        if code == 200:
            release = data
    if not release:
        code, data = gh.get(f"/repos/{owner}/{repo}/releases/latest")
        if code == 200:
            release = data

    # Fallback: no releases -> use latest tag
    if not release:
        code, tags = gh.get(f"/repos/{owner}/{repo}/tags", params={"per_page": 1})
        if code != 200 or not isinstance(tags, list) or not tags:
            raise ValueError("No releases or tags found for this repository.")
        latest_tag = tags[0].get("name")
        release = {
            "tag_name": latest_tag,
            "name": latest_tag,
            "body": "",
            "html_url": f"https://github.com/{owner}/{repo}/releases/tag/{latest_tag}",
            "published_at": None,
            "draft": False,
            "prerelease": False,
            "author": {"login": repo_data.get("owner", {}).get("login")},
            "id": None,
        }

    current_tag = release.get("tag_name")

    # Determine previous release tag if available
    prev_tag = None
    code, releases = gh.get(f"/repos/{owner}/{repo}/releases", params={"per_page": 30})
    if code == 200 and isinstance(releases, list):
        tags = [r.get("tag_name") for r in releases if r.get("tag_name")]
        if current_tag in tags:
            idx = tags.index(current_tag)
            if idx + 1 < len(tags):
                prev_tag = tags[idx + 1]

    # Compare commits between previous and current tags
    compare = {}
    commits: list[dict[str, Any]] = []
    if prev_tag and current_tag:
        code, compare_data = gh.get(f"/repos/{owner}/{repo}/compare/{prev_tag}...{current_tag}", timeout=45)
        if code == 200 and isinstance(compare_data, dict):
            compare = compare_data
            commits = (compare_data.get("commits") or [])[:max_commits]

    # Deep mode: fetch README excerpt for better context
    readme_excerpt = ""
    if mode == "deep":
        readme_code, readme = gh.get(f"/repos/{owner}/{repo}/readme")
        if readme_code == 200 and isinstance(readme, dict):
            content = readme.get("content", "")
            if content:
                try:
                    text = base64.b64decode(content).decode("utf-8", errors="ignore")
                    readme_excerpt = text[:1200].strip()
                except Exception:
                    pass

    # Collect candidate PR numbers
    pr_numbers: set[int] = set()
    release_body = release.get("body") or ""
    pr_numbers.update(extract_issue_or_pr_numbers(release_body))
    for c in commits:
        msg = (c.get("commit") or {}).get("message", "")
        # Conventional merge style: "... (#123)"
        pr_numbers.update({int(x) for x in re.findall(r"\(#(\d+)\)", msg)})
        pr_numbers.update({int(x) for x in re.findall(r"pull request #(\d+)", msg, re.IGNORECASE)})

    prs: list[dict[str, Any]] = []
    if include_prs and pr_numbers:
        for n in sorted(pr_numbers)[:max_prs]:
            code, pr = gh.get(f"/repos/{owner}/{repo}/pulls/{n}")
            if code == 200 and isinstance(pr, dict):
                prs.append({
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "url": pr.get("html_url"),
                    "author": (pr.get("user") or {}).get("login"),
                    "merged_at": pr.get("merged_at"),
                    "labels": [lb.get("name") for lb in pr.get("labels") or []],
                    "body": pr.get("body") or "",
                })

    # Collect issue numbers from release + PR descriptions
    issue_numbers: set[int] = set()
    if include_issues:
        issue_numbers.update(extract_issue_or_pr_numbers(release_body))
        for pr in prs:
            issue_numbers.update(extract_issue_or_pr_numbers(pr.get("body", "")))

    issues: list[dict[str, Any]] = []
    if include_issues and issue_numbers:
        for n in sorted(issue_numbers)[:max_issues]:
            code, issue = gh.get(f"/repos/{owner}/{repo}/issues/{n}")
            if code == 200 and isinstance(issue, dict):
                # Exclude PR records returned by issues API
                if issue.get("pull_request"):
                    continue
                issues.append({
                    "number": issue.get("number"),
                    "title": issue.get("title"),
                    "url": issue.get("html_url"),
                    "state": issue.get("state"),
                    "labels": [lb.get("name") for lb in issue.get("labels") or []],
                })

    return {
        "repo": repo_data,
        "release": release,
        "prev_tag": prev_tag,
        "compare": compare,
        "commits": commits,
        "prs": prs,
        "issues": issues,
        "readme_excerpt": readme_excerpt,
    }


def build_highlights(context: dict[str, Any]) -> dict[str, Any]:
    release = context["release"]
    commits = context["commits"]
    prs = context["prs"]
    issues = context["issues"]

    type_counts: dict[str, int] = {}
    for c in commits:
        msg = (c.get("commit") or {}).get("message", "")
        t = summarize_commit_type(msg)
        type_counts[t] = type_counts.get(t, 0) + 1

    top_types = sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True)
    top_types = [f"{k}:{v}" for k, v in top_types[:4] if k != "other" or v > 0]

    commit_samples = []
    for c in commits[:10]:
        msg = ((c.get("commit") or {}).get("message") or "").splitlines()[0]
        commit_samples.append({
            "sha": (c.get("sha") or "")[:8],
            "message": msg,
            "url": c.get("html_url"),
        })

    breaking = detect_breaking_changes(release.get("body") or "", commits)

    return {
        "stats": {
            "commits": len(commits),
            "prs": len(prs),
            "issues": len(issues),
        },
        "top_commit_types": top_types,
        "breaking_changes": breaking,
        "commit_samples": commit_samples,
    }


def build_markdown_report(target: RepoTarget, context: dict[str, Any], highlights: dict[str, Any]) -> str:
    repo = context["repo"]
    release = context["release"]
    prev_tag = context["prev_tag"]
    compare = context["compare"]
    prs = context["prs"]
    issues = context["issues"]
    commit_samples = highlights["commit_samples"]
    breaking = highlights["breaking_changes"]

    owner = target.owner
    repo_name = target.repo
    tag = release.get("tag_name") or "unknown"
    name = release.get("name") or tag
    html_url = release.get("html_url") or f"https://github.com/{owner}/{repo_name}/releases/tag/{tag}"
    published = release.get("published_at") or "N/A"
    compare_url = compare.get("html_url") if isinstance(compare, dict) else None

    lines: list[str] = []
    lines.append(f"# Git Release Notes: {owner}/{repo_name}")
    lines.append("")
    lines.append("## Snapshot")
    lines.append(f"- Release: **{name}** (`{tag}`)")
    lines.append(f"- URL: {html_url}")
    lines.append(f"- Published: {published}")
    lines.append(f"- Repo: {repo.get('html_url')}")
    lines.append(f"- Previous Tag: `{prev_tag or 'N/A'}`")
    lines.append(f"- Compare: {compare_url or 'N/A'}")
    lines.append(f"- Generated: {now_iso()}")
    lines.append("")

    lines.append("## Executive Summary")
    types = ", ".join(highlights.get("top_commit_types") or []) or "N/A"
    stats = highlights.get("stats") or {}
    lines.append(
        f"- Scope: {stats.get('commits', 0)} commits, {stats.get('prs', 0)} PRs, {stats.get('issues', 0)} linked issues."
    )
    lines.append(f"- Main change themes: {types}.")
    if breaking:
        lines.append(f"- Risk: Potential breaking changes detected ({len(breaking)}). Review required before upgrade.")
    else:
        lines.append("- Risk: No explicit breaking-change markers detected.")
    lines.append("")

    if breaking:
        lines.append("## Breaking Changes (Detected)")
        for item in breaking[:12]:
            lines.append(f"- {item}")
        lines.append("")

    body = (release.get("body") or "").strip()
    if body:
        lines.append("## Upstream Release Notes (Raw)")
        lines.append(body[:8000])
        lines.append("")

    if prs:
        lines.append("## Linked Pull Requests")
        for pr in prs[:30]:
            labels = ", ".join(pr.get("labels") or [])
            label_text = f" — labels: {labels}" if labels else ""
            lines.append(f"- #{pr.get('number')} [{pr.get('title')}]({pr.get('url')}) by `{pr.get('author')}`{label_text}")
        lines.append("")

    if issues:
        lines.append("## Linked Issues")
        for issue in issues[:30]:
            labels = ", ".join(issue.get("labels") or [])
            label_text = f" — labels: {labels}" if labels else ""
            lines.append(
                f"- #{issue.get('number')} [{issue.get('title')}]({issue.get('url')}) "
                f"(state: {issue.get('state')}){label_text}"
            )
        lines.append("")

    if commit_samples:
        lines.append("## Notable Commits")
        for c in commit_samples:
            lines.append(f"- `{c.get('sha')}` [{c.get('message')}]({c.get('url')})")
        lines.append("")

    readme_excerpt = (context.get("readme_excerpt") or "").strip()
    if readme_excerpt:
        lines.append("## Project Context (README Excerpt)")
        lines.append(readme_excerpt)
        lines.append("")

    lines.append("## Action Checklist")
    lines.append("- Review breaking changes and migration notes.")
    lines.append("- Validate dependency/API compatibility in staging.")
    lines.append("- Scan linked PRs/issues for behavior changes and regressions.")
    lines.append("- Run smoke/integration tests after upgrade.")
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def save_report_to_stash(report_md: str, owner: str, repo: str, tag: str) -> tuple[str | None, str | None, str | None]:
    """Save markdown report to stash and return (stash_ref, space_id, filename)."""
    try:
        space, _ = open_space(scope="session", labels=["git_release_notes", owner, repo])
        stash_file = StashFile(space)
        filename = sanitize_name(f"{owner}_{repo}_{tag}_release_notes.md", "release_notes.md")
        saved = stash_file.save_text(
            content=report_md,
            name=filename,
            on_conflict="version",
            tags=["github", "release_notes", owner, repo],
            tool_origin="git_release_notes",
        )
        return saved.get("ref"), space.space_id, saved.get("name")
    except Exception:
        return None, None, None


def save_report_to_canvas(title: str, content: str, source_query: str) -> tuple[str | None, str | None]:
    """Create a canvas page by calling canvas tool script."""
    canvas_script = Path(__file__).parent / "canvas.py"
    if not canvas_script.exists():
        return None, "canvas.py not found"

    project_root = Path(__file__).parent.parent
    payload = {
        "action": "create",
        "title": title,
        "content": content,
        "tags": ["github", "release_notes"],
        "source_query": source_query,
    }
    try:
        result = subprocess.run(
            ["python3", str(canvas_script), json.dumps(payload)],
            capture_output=True,
            text=True,
            timeout=45,
            cwd=str(project_root),
        )
        if result.returncode != 0:
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            if stdout:
                try:
                    failed_result = json.loads(stdout)
                    if isinstance(failed_result, dict) and failed_result.get("error"):
                        return None, str(failed_result["error"])
                except json.JSONDecodeError:
                    pass
            return None, stderr or stdout or "canvas tool failed"
        parsed = json.loads(result.stdout or "{}")
        if not parsed.get("ok"):
            return None, parsed.get("error") or "canvas create failed"
        page_id = (parsed.get("data") or {}).get("page_id")
        return page_id, None
    except Exception as e:
        return None, str(e)


def remember_artifact(target: RepoTarget, tag: str, stash_ref: str | None, page_id: str | None):
    """Store artifact references for recall."""
    if not stash_ref and not page_id:
        return
    try:
        db = MemoryDB()
        key = f"release_notes_{target.owner}_{target.repo}_{tag}"
        value_parts = [f"Release notes summary for {target.owner}/{target.repo} {tag}."]
        if stash_ref:
            value_parts.append(f"STASH: {stash_ref}.")
        if page_id:
            value_parts.append(f"CANVAS_PAGE: {page_id}.")
        db.remember(
            key=key,
            value=" ".join(value_parts),
            category="stash_artifact",
            importance=6,
            source="git_release_notes",
            metadata={
                "owner": target.owner,
                "repo": target.repo,
                "tag": tag,
                "stash_ref": stash_ref,
                "canvas_page_id": page_id,
                "type": "release_notes",
                "tags": ["github", "release_notes"],
            },
        )
    except Exception:
        pass


def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)

        load_config()

        target_input = str(args.get("target", "")).strip()
        explicit_tag = str(args.get("tag", "")).strip() or None
        mode = str(args.get("mode", "deep")).strip().lower()
        mode = mode if mode in {"quick", "deep"} else "deep"

        include_prs = bool(args.get("include_prs", True))
        include_issues = bool(args.get("include_issues", True))
        max_commits = clamp(int(args.get("max_commits", 25) or 25), 1, 100)
        max_prs = clamp(int(args.get("max_prs", 20) or 20), 1, 100)
        max_issues = clamp(int(args.get("max_issues", 20) or 20), 1, 100)
        save_to_canvas = bool(args.get("save_to_canvas", True))
        save_to_stash = bool(args.get("save_to_stash", True))
        canvas_title = str(args.get("canvas_title", "")).strip()

        target = parse_repo_target(target_input, explicit_tag)

        gh = GitHubClient()
        context = fetch_release_context(
            gh=gh,
            target=target,
            mode=mode,
            max_commits=max_commits,
            max_prs=max_prs,
            max_issues=max_issues,
            include_prs=include_prs,
            include_issues=include_issues,
        )
        highlights = build_highlights(context)
        release = context["release"]
        tag = release.get("tag_name") or "unknown"
        report_md = build_markdown_report(target, context, highlights)

        stash_ref = None
        stash_space_id = None
        stash_name = None
        if save_to_stash:
            stash_ref, stash_space_id, stash_name = save_report_to_stash(report_md, target.owner, target.repo, tag)

        canvas_page_id = None
        canvas_error = None
        if save_to_canvas:
            title = canvas_title or f"Release Notes: {target.owner}/{target.repo} {tag}"
            canvas_page_id, canvas_error = save_report_to_canvas(title=title, content=report_md, source_query=target_input)
            if not canvas_page_id:
                raise RuntimeError(
                    "Failed to save release notes to Canvas: "
                    f"{canvas_error or 'unknown Canvas error'}"
                )

        remember_artifact(target=target, tag=tag, stash_ref=stash_ref, page_id=canvas_page_id)

        stats = highlights.get("stats") or {}
        breaking = highlights.get("breaking_changes") or []
        speech = (
            f"Analyzed {target.owner}/{target.repo} {tag}. "
            f"{stats.get('commits', 0)} commits, {stats.get('prs', 0)} PRs, {stats.get('issues', 0)} issues."
        )
        if breaking:
            speech += f" Found {len(breaking)} potential breaking changes."
        if canvas_page_id:
            speech += " Saved report to canvas."
        if stash_ref:
            speech += " Saved markdown report to stash."

        output = {
            "ok": True,
            "speech": speech,
            "data": {
                "owner": target.owner,
                "repo": target.repo,
                "release_tag": tag,
                "release_name": release.get("name") or tag,
                "release_url": release.get("html_url"),
                "published_at": release.get("published_at"),
                "previous_tag": context.get("prev_tag"),
                "stats": stats,
                "top_commit_types": highlights.get("top_commit_types"),
                "breaking_changes": breaking,
                "notable_prs": context.get("prs", [])[:10],
                "linked_issues": context.get("issues", [])[:10],
                "notable_commits": highlights.get("commit_samples", [])[:10],
                "stash_ref": stash_ref,
                "stash_space_id": stash_space_id,
                "stash_filename": stash_name,
                "canvas_page_id": canvas_page_id,
                "canvas_error": canvas_error,
                "mode": mode,
            },
        }
        print(json.dumps(output))

    except Exception as e:
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "speech": f"Failed to build release notes: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
