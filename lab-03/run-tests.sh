#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONPATH="$root/lab-03${PYTHONPATH:+:$PYTHONPATH}"
python3 -m unittest discover -s "$root/lab-03/tests" -v
cd "$root/lab-03/organizer"
go test -count=1 -v ./...
