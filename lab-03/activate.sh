#!/usr/bin/env bash
# Source this file from any directory. No services or hooks are enabled implicitly.
set -euo pipefail
LAB03_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PATH="$LAB03_ROOT/.venv/go/bin:$LAB03_ROOT/.venv/bin:$PATH"
export GOPATH="$LAB03_ROOT/.venv/gopath" GOCACHE="$LAB03_ROOT/.venv/go-cache"
