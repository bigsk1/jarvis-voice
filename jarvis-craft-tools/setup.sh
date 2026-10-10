#!/usr/bin/env bash
set -euo pipefail
craft_source=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$craft_source/scripts/setup_gateway.py" "$@"
