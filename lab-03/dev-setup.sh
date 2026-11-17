#!/usr/bin/env bash
set -euo pipefail
# Development dependencies are isolated in ignored checkout-local directories.
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r lab-03/requirements-dev.txt
mkdir -p lab-03/var lab-03/bin
if [[ ! -x .venv/go/bin/go ]]; then
    case "$(uname -s)-$(uname -m)" in
        Linux-x86_64) arch=amd64; checksum=65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40;;
        Linux-aarch64) arch=arm64; checksum=a06e99309dbcbdca1a8ccd2282c3ee146e55930886e26b4f1193269587165f49;;
        *) printf 'Unsupported platform for pinned Go bootstrap; install Go 1.24+ manually\n' >&2; exit 2;;
    esac
    archive=$(mktemp)
    trap 'rm -f -- "$archive"' EXIT
    curl --fail --location --silent --show-error "https://go.dev/dl/go1.27.3.linux-$arch.tar.gz" -o "$archive"
    printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c -
    tar -xzf "$archive" -C .venv
fi
# The image may contain GNU Go (the board game); put the language toolchain first.
export PATH="$root/.venv/go/bin:$root/.venv/bin:$PATH"
export GOPATH="$root/.venv/gopath" GOCACHE="$root/.venv/go-cache"
go version
GOBIN="$root/.venv/bin" go install github.com/aptible/supercronic@v0.2.34
printf 'Dependencies ready. Activate with: source lab-03/activate.sh\n'
