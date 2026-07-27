#!/bin/sh
set -eu

PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
exec python3 "$PACKAGE_DIR/scripts/check_env.py" "${1:-$PACKAGE_DIR/.env}"
