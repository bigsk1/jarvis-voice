"""One-shot human and agent CLI for the full Jarvis orchestrator.

Keep imports lightweight so help and argument validation never initialize MCP.
"""
from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parser(*, legacy: bool = False) -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        prog='orchestrator_v2.py' if legacy else 'jarvis-cli',
        description='Run a natural-language request through the full Jarvis app. Prints the answer by default.',
        epilog='Agent usage: jarvis-cli --json --no-context --stdin. See jarvis-cli/README.md.',
        allow_abbrev=False,
    )
    if legacy:
        cli.add_argument('mode', choices=('cloud', 'local'), help='Selected Jarvis configuration')
    else:
        cli.add_argument('--mode', choices=('cloud', 'local'), default='cloud', help='Selected configuration (default: cloud)')
    cli.add_argument('request', nargs='*', help='Natural-language request; quote it as one argument')
    cli.add_argument('--stdin', action='store_true', help='Read the request from stdin instead of arguments')
    cli.add_argument('--json', action='store_true', help='Print one complete JSON result, including status, tools, artifacts and errors')
    cli.add_argument('--verbose', action='store_true', help='Show startup, MCP and tool diagnostics on stderr')
    cli.add_argument('--no-context', action='store_true', help='Disable automatic recent-conversation context for this request')
    cli.add_argument('--no-tools', action='store_true', help='Answer without client tools, workflows or provider-hosted tools')
    cli.add_argument('--exclude-tool', action='append', default=[], metavar='NAME', help='Exclude a tool for this request; repeatable')
    cli.add_argument('--prompt', metavar='NAME', help='Load jarvis-web/data/prompts/NAME.md (including personal/NAME)')
    cli.add_argument('--speak', action='store_true', help='Also speak the final answer through the configured TTS provider')
    cli.add_argument('--voice-progress', action='store_true', help='Honor configured spoken progress updates (used by wake-word wrappers)')
    cli.add_argument('--debug-thinking', action='store_true', help='Enable visible reasoning and show it on stderr when the provider supports it')
    cli.add_argument('--feedback', action='store_true', help='Collect LLM QA feedback; show a summary on stderr or include it in JSON')
    return cli


@contextlib.contextmanager
def diagnostics(verbose: bool):
    """Contain Python and inherited subprocess output; stdout is a result channel."""
    target = sys.stderr if verbose else open(os.devnull, 'w')
    saved = []
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        # Python-only streams in tests may not expose a file descriptor.
        try:
            target_fd = target.fileno()
        except (AttributeError, OSError, ValueError):
            target_fd = None
        if target_fd is not None:
            for fd in (1, 2):
                saved.append((fd, os.dup(fd)))
                os.dup2(target_fd, fd)
        with contextlib.redirect_stdout(target), contextlib.redirect_stderr(target):
            yield
    finally:
        target.flush()
        for fd, original in reversed(saved):
            os.dup2(original, fd)
            os.close(original)
        if not verbose:
            target.close()


def _prompt_text(name: str, root: Path = ROOT) -> str:
    directory = (root / 'jarvis-web/data/prompts').resolve()
    path = (directory / (name + '.md')).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise ValueError(f'Prompt {name!r} not found under jarvis-web/data/prompts; use a name without .md')
    return path.read_text()


def _feedback(orch, result, transcript, mode):
    from config_loader import (
        DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT,
        DEFAULT_JARVIS_QA_WORD_LIMIT,
        get_config_value,
        get_int,
    )
    from feedback import FeedbackCollector

    tools_used = result.get('tools_used', [])
    if isinstance(tools_used, str):
        tools_used = [tools_used]
    relevant = set(tools_used)
    for keyword, names in {
        'time': ['get_time'], 'weather': ['weather'],
        'bitcoin': ['crypto_price'], 'crypto': ['crypto_price'], 'price': ['crypto_price'],
        'memory': ['semantic_recall', 'search_memory', 'remember'], 'remember': ['semantic_recall', 'search_memory', 'remember'],
    }.items():
        if keyword in transcript.lower():
            relevant.update(names)
    descriptions = {}
    for name in relevant:
        try:
            tool = orch.registry.get_tool(name)
            if tool:
                descriptions[name] = tool.description
        except Exception:
            continue
    style = get_config_value('JARVIS_RESPONSE_STYLE', 'auto')
    qa_limit = get_int('JARVIS_QA_WORD_LIMIT', DEFAULT_JARVIS_QA_WORD_LIMIT)
    multi_limit = get_int('JARVIS_MULTI_TURN_WORD_LIMIT', DEFAULT_JARVIS_MULTI_TURN_WORD_LIMIT)
    style_explanations = {
        'casual': f'Short voice-friendly output. Tool confirmations stay at 35 words max, Q&A is capped at {qa_limit}, multi-turn summaries at {multi_limit}.',
        'auto': f'Smart mode. Search tools get condensed (no URLs), complex tools keep full details. Q&A cap is {qa_limit}, multi-turn cap is {multi_limit}.',
        'detailed': 'FULL LLM response preserved. URLs ARE INCLUDED. Verbose output is EXPECTED and CORRECT.',
    }
    context = (
        f'Interface: cli/voice; mode={mode}\n'
        f'Auto-Context: {orch.auto_context_enabled} '
        f'(window={orch.auto_context_window}, minutes={orch.auto_context_minutes})\n'
        f'Response Style: {style}\n{style_explanations.get(style, "Unknown style")}\n'
        f'Do NOT penalize verbose output or URLs if style is detailed.\n'
        f'Tools Available: {len(orch.registry.list_tools())}'
    )
    feedback = FeedbackCollector(mode).collect(
        query=transcript, result=result, tools_used=tools_used,
        num_tools=len(orch.registry.list_tools()),
        system_prompt=getattr(orch.router, 'system_prompt', None),
        tool_descriptions=descriptions,
        intelligence_insights=result.get('intelligence_context', 'Intelligence insights not captured.'),
        config_context=context, session_id=orch.session_id,
    )
    result['feedback'] = feedback
    rating = feedback.get('rating')
    experience_id = result.get('experience_id', -1)
    if rating is not None and experience_id > 0:
        from intelligence_hooks import update_experience_from_feedback
        update_experience_from_feedback(
            experience_id=experience_id, feedback_rating=rating,
            feedback_summary=feedback.get('summary'),
            feedback_details={key: feedback.get(key, {} if key == 'tool_ratings' else [] if key in ('issues', 'suggestions') else '')
                              for key in ('positive', 'issues', 'suggestions', 'analysis', 'tool_ratings')},
        )


def _speak(result, mode):
    import subprocess

    from config_loader import get_config_value
    from security_utils import sanitize_for_speech
    from tts_style_tags import speech_tag_options

    text = sanitize_for_speech(
        result.get('speech', ''),
        **speech_tag_options(get_config_value('TTS_PROVIDER', ''), get_config_value('ELEVENLABS_TTS_MODEL', '')),
    )
    if text:
        script = ROOT / 'bin' / ('say.sh' if mode == 'cloud' else 'say-local.sh')
        subprocess.run([str(script), text], check=True)


def _answer(result):
    import re

    from tts_style_tags import all_inline_speech_tags, all_wrapping_speech_tags

    text = str(result.get('raw_llm_response') or result.get('speech') or result.get('error') or '')
    for tag in all_inline_speech_tags():
        text = re.sub(r'\[' + re.escape(tag) + r'\]', '', text, flags=re.IGNORECASE)
    for tag in all_wrapping_speech_tags():
        text = re.sub(r'</?' + re.escape(tag) + r'>', '', text, flags=re.IGNORECASE)
    return text.strip()


def _show_feedback(feedback):
    """Explicit human QA output, leaving stdout reserved for the answer."""
    print(f'Feedback rating: {feedback.get("rating", "N/A")}/5', file=sys.stderr)
    if feedback.get('summary'):
        print(f'Summary: {feedback["summary"]}', file=sys.stderr)
    for issue in feedback.get('issues') or []:
        if isinstance(issue, dict):
            print(f'Issue [{issue.get("category", "other")}]: {issue.get("description", "")}', file=sys.stderr)
            if issue.get('suggestion'):
                print(f'Suggestion: {issue["suggestion"]}', file=sys.stderr)
        else:
            print(f'Issue: {issue}', file=sys.stderr)


def _show_progress(event_type, **details):
    """Expose actual orchestrator events even when stderr is redirected to a file."""
    import json

    print(f'[Jarvis {event_type}] {json.dumps(details, ensure_ascii=False, default=str)}', file=sys.stderr)


def main(argv=None, *, legacy=False, orchestrator_factory=None, load_config_fn=None) -> int:
    import json

    cli = parser(legacy=legacy)
    args = cli.parse_args(argv)
    if args.stdin and args.request:
        cli.error('Use either request arguments or --stdin, not both')
    transcript = sys.stdin.read() if args.stdin else ' '.join(args.request)
    if not transcript.strip():
        cli.error('Provide a nonempty request or pipe one with --stdin')
    if args.prompt:
        try:
            prompt = _prompt_text(args.prompt)
        except ValueError as exc:
            cli.error(str(exc))
        transcript = f'[CONTEXT - Use these guidelines for the request below]\n\n{prompt}\n\n[END CONTEXT]\n\nUser\'s request: {transcript}'

    os.environ['JARVIS_MODE'] = args.mode
    os.environ['JARVIS_JSON_MODE'] = '1'
    if not args.voice_progress:
        os.environ['JARVIS_OVERRIDE_STATUS_UPDATES_ENABLED'] = 'false'
    if args.no_context:
        os.environ['JARVIS_OVERRIDE_AUTO_CONTEXT_ENABLED'] = 'false'
    if args.debug_thinking:
        os.environ['JARVIS_OVERRIDE_JARVIS_DEBUG_THINKING'] = '1'
    # No progress chatter unless requested, even with a debug-enabled ENV.
    os.environ['JARVIS_OVERRIDE_JARVIS_DEBUG'] = 'true' if args.verbose else 'false'
    # Legacy routing/tool diagnostics test presence in os.environ, rather than
    # the scoped config getter. Keep both views consistent with the CLI flag.
    if args.verbose:
        os.environ['JARVIS_DEBUG'] = '1'
    else:
        os.environ.pop('JARVIS_DEBUG', None)
    orch = None
    code = 1
    with diagnostics(args.verbose):
        try:
            sys.path.insert(0, str(ROOT))
            sys.path.insert(0, str(ROOT / 'lib'))
            sys.path.insert(0, str(ROOT / 'orchestrator'))
            from config_loader import get_config_value, get_float, load_config

            from lib.background_tasks.admission import reject_background_result
            if load_config_fn is None and not (ROOT / 'config' / (args.mode + '.env')).is_file():
                raise ValueError(f'Create config/{args.mode}.env through normal Jarvis setup before using this mode')
            (load_config_fn or load_config)(args.mode)
            if orchestrator_factory is None:
                from orchestrator_v2 import Orchestrator
                orchestrator_factory = Orchestrator
            excluded = os.environ.get('JARVIS_SELF_PLAY_EXCLUDED_TOOLS') or os.environ.get('JARVIS_EXCLUDED_TOOLS', '')
            exclusions = sorted(set(args.exclude_tool) | {name.strip() for name in excluded.split(',') if name.strip()})
            orch = orchestrator_factory(args.mode)
            progress_setter = getattr(orch, 'set_progress_callback', None)
            if args.verbose and callable(progress_setter):
                progress_setter(_show_progress)
            options = {'excluded_tools': exclusions}
            if args.no_tools:
                options['tool_policy'] = 'none'
            result = reject_background_result(orch.process(transcript, **options))
            code = 0 if result.get('ok') else 1
            collect = args.feedback
            if not collect and get_config_value('FEEDBACK_RANDOM_ENABLED', 'false').lower() == 'true':
                import random
                collect = random.random() < get_float('FEEDBACK_RANDOM_CHANCE', 0.0)
            if collect:
                try:
                    _feedback(orch, result, transcript, args.mode)
                except Exception as exc:
                    result['feedback_error'] = str(exc)
            if args.speak:
                try:
                    _speak(result, args.mode)
                except Exception as exc:
                    result['tts_error'] = str(exc)
                    code = 1
        except KeyboardInterrupt:
            code = 130
            result = {'ok': False, 'cancelled': True, 'completion': 'unknown', 'tools_used': [],
                      'speech': 'Interrupted. Remote work may still be running; inspect accepted jobs before retrying.',
                      'error': 'CLI interrupted'}
        except Exception as exc:
            import traceback
            if args.verbose:
                traceback.print_exc()
            result = {'ok': False, 'completion': 'unknown', 'tools_used': [],
                      'speech': f'Jarvis could not complete the request: {exc}',
                      'error': str(exc), 'error_type': type(exc).__name__}
        finally:
            registry = getattr(orch, 'registry', None)
            if registry is not None:
                try:
                    registry.cleanup()
                except Exception as exc:
                    print(f'CLI cleanup warning: {exc}', file=sys.stderr)

    if args.debug_thinking and result.get('thinking'):
        from thinking import format_thinking_display
        print(format_thinking_display(result['thinking']), file=sys.stderr)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(_answer(result))
        if args.feedback and result.get('feedback'):
            _show_feedback(result['feedback'])
        for key in ('feedback_error', 'tts_error'):
            if result.get(key):
                print(f'{key}: {result[key]}', file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
