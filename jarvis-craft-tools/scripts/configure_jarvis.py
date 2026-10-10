#!/usr/bin/env python3
"""Copy private gateway settings into one Jarvis mode without printing secrets."""
import argparse
import json
import os
from pathlib import Path

KEYS = ('CRAFT_API_URL', 'CRAFT_API_KEY', 'CRAFT_CA_BUNDLE')

def read_settings(path):
    settings = {}
    for line in path.read_text().splitlines():
        name, separator, value = line.partition('=')
        if separator and name in KEYS:
            settings[name] = json.loads(value) if value.startswith('"') else value.strip()
    if not settings.get('CRAFT_API_URL') or not settings.get('CRAFT_API_KEY'):
        raise ValueError('Settings file must contain the gateway URL and API key')
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--mode', choices=('cloud','local'), required=True)
    parser.add_argument('--jarvis-root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--api-url', help='Override the host-side URL with the address reachable from Jarvis')
    parser.add_argument('--ca-bundle', type=Path, help='Client-side path; copy only the public CA before configuring')
    args = parser.parse_args()
    values = read_settings(args.settings.expanduser())
    if args.api_url:
        values['CRAFT_API_URL'] = args.api_url
    if args.ca_bundle:
        bundle = args.ca_bundle.expanduser().resolve()
        if not bundle.is_file():
            parser.error('CA bundle must already exist on the Jarvis client')
        values['CRAFT_CA_BUNDLE'] = str(bundle)
    elif values.get('CRAFT_CA_BUNDLE') and not Path(values['CRAFT_CA_BUNDLE']).is_file():
        parser.error('Set --ca-bundle to the client-side public CA path')
    target = args.jarvis_root.expanduser().resolve() / 'config' / (args.mode + '.env')
    if not target.is_file():
        parser.error('Create the selected mode ENV from its example first; this helper does not configure the rest of Jarvis')
    lines = [line for line in target.read_text().splitlines() if line.partition('=')[0].strip() not in KEYS]
    lines += ['', '# Optional Craft Gateway connection', *[name + '=' + json.dumps(values.get(name, '')) for name in KEYS]]
    temporary = target.with_name(target.name + '.craft-new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write('\n'.join(lines) + '\n')
    temporary.replace(target)
    target.chmod(0o600)
    print(f'Configured Craft in {args.mode} mode. Connection values were not printed. Restart/reload Jarvis and sync tools for this mode.')

if __name__ == '__main__':
    main()
