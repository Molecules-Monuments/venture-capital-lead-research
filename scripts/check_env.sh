#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu

# Thin shell entry point for the environment validator: hand the .env file (arg
# 1, or the package default) to check_env.py, which validates every required
# value fail-closed without evaluating any shell code from the file.
PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
exec python3 "$PACKAGE_DIR/scripts/check_env.py" "${1:-$PACKAGE_DIR/.env}"
