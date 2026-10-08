"""Shared yt-dlp executable, JavaScript runtime, and subprocess environment."""

import importlib.util
import os
import shutil
import sys


def resolve_yt_dlp_command() -> list[str]:
    """Use the active Python environment; support standalone installations too."""
    if importlib.util.find_spec('yt_dlp') is not None:
        return [sys.executable, '-m', 'yt_dlp']
    return [shutil.which('yt-dlp') or 'yt-dlp']


def runtime_args(proxy: str | None) -> list[str]:
    """Enable a supported JS engine and make the selected transport explicit."""
    args = []
    for runtime in ('deno', 'node'):
        path = shutil.which(runtime)
        if path:
            args.extend(['--js-runtimes', f'{runtime}:{path}'])
            break
    # An absent flag lets yt-dlp reuse HTTP_PROXY even on a direct retry.
    return args + ['--proxy', proxy or '']


def subprocess_environment() -> dict[str, str]:
    """External JS engines do not need Jarvis's API keys or account secrets."""
    allowed = {
        'PATH', 'HOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'SYSTEMROOT', 'WINDIR',
        'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR', 'TMP', 'TEMP',
        'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'XDG_CACHE_HOME',
        'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE',
    }
    return {key: value for key, value in os.environ.items() if key in allowed}
