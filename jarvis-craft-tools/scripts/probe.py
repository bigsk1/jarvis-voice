#!/usr/bin/env python3
"""Authenticated capability check from any client using only Python's stdlib."""
import argparse
import json
import ssl
import urllib.request
from pathlib import Path

from configure_jarvis import read_settings


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, required=True)
    parser.add_argument('--api-url')
    parser.add_argument('--ca-bundle', type=Path)
    args=parser.parse_args()
    values=read_settings(args.settings.expanduser())
    url=(args.api_url or values['CRAFT_API_URL']).rstrip('/')
    bundle=str(args.ca_bundle) if args.ca_bundle else values.get('CRAFT_CA_BUNDLE')
    context=ssl.create_default_context(cafile=bundle or None)
    request=urllib.request.Request(url+'/capabilities',headers={'Authorization':'Bearer '+values['CRAFT_API_KEY']})
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=context))
    with opener.open(request,timeout=10) as response:
        result=json.loads(response.read(2*1024**2))
    print(json.dumps({'protocol_version':result['protocol_version'], 'gateway_version':result['gateway_version'],
                      'apps':result['apps'], 'limits':result['limits']},indent=2))

if __name__ == '__main__':
    main()
