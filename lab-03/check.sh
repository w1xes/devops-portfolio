#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
shellcheck lab-03/*.sh lab-03/hooks/pre-commit lab-03/hooks/pre-push
ruff check lab-03
if [[ -n $(gofmt -l lab-03/organizer/*.go) ]]; then
    printf 'Go files need gofmt\n' >&2
    exit 1
fi
(cd lab-03/organizer && go vet ./...)
./lab-03/run-tests.sh
mkdir -p lab-03/bin
(cd lab-03/organizer && CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o ../bin/organizer .)
