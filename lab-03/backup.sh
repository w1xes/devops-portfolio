#!/usr/bin/env bash
set -euo pipefail

source_dir='' dest='' keep=5 dry_run=false partial=''
log_file=${BACKUP_LOG:-backup.log}
# A dry run must not create even a log or lock file, including on invalid input.
for arg in "$@"; do [[ $arg != --dry-run ]] || dry_run=true; done
log() {
    local line
    printf -v line '%s action=backup %s' "$(date -u +%FT%TZ)" "$*"
    printf '%s\n' "$line" >&2
    if ! "$dry_run"; then
        printf '%s\n' "$line" >> "$log_file" || { printf 'Cannot write log: %s\n' "$log_file" >&2; exit 7; }
    fi
}
finish() {
    local rc=$?
    trap - EXIT
    [[ -z $partial ]] || rm -f -- "$partial"
    log "result=exit code=$rc"
    exit "$rc"
}
trap finish EXIT
fail() { log "result=error message=$2"; exit "$1"; }
usage() {
    cat <<'HELP'
Create a compressed backup and rotate only backups of the same canonical source.
Usage: backup.sh --source DIR --dest DIR [--keep N] [--dry-run] [--help]
  --source DIR  Readable source directory (required)
  --dest DIR    Backup directory, outside source (required; created as needed)
  --keep N      Positive number of newest archives to retain (default: 5)
  --dry-run     Print creation/deletion plan; do not change any files
  --help        Show this help
Environment: BACKUP_LOG (default: ./backup.log; parent must exist).
Example: ./backup.sh --source 'my project' --dest '/tmp/my backups' --keep 3
Exit: 0 success; 2 arguments; 3 source; 4 destination/lock; 5 archive;
      6 rotation; 7 log I/O. GNU tar, coreutils, util-linux flock required.
HELP
}
while (($#)); do
    case "$1" in
        --source|--dest|--keep)
            (($# >= 2)) && [[ $2 != --* && -n $2 ]] || fail 2 "Missing value for $1"
            case "$1" in --source) source_dir=$2;; --dest) dest=$2;; --keep) keep=$2;; esac
            shift 2;;
        --dry-run) shift;;
        --help) usage; exit 0;;
        *) fail 2 "Unknown argument: $1";;
    esac
done
[[ -n $source_dir && -n $dest ]] || fail 2 '--source and --dest are required'
[[ $keep =~ ^[1-9][0-9]{0,8}$ ]] || fail 2 '--keep must be an integer from 1 to 999999999'
[[ -d $source_dir && -r $source_dir && -x $source_dir ]] || fail 3 'Source must be a readable/searchable directory'
source_dir=$(realpath -e -- "$source_dir") || fail 3 'Cannot resolve source'
dest=$(realpath -m -- "$dest") || fail 4 'Cannot resolve destination'
[[ $source_dir != / && $dest != "$source_dir" && $dest != "$source_dir/"* ]] || fail 4 'Destination must be outside source; root source is unsupported'
[[ ! -e $dest || -d $dest ]] || fail 4 'Destination is not a directory'
base=$(basename -- "$source_dir")
identity=$(printf '%s' "$source_dir" | sha256sum)
identity=${identity:0:12}
prefix="$base-$identity-"
if ! "$dry_run"; then
    mkdir -p -- "$dest" || fail 4 'Cannot create destination'
    # Serialize creation/rotation; never delete the lock inode while other writers wait.
    exec 9>"$dest/.backup-$identity.lock" || fail 4 'Cannot open lock'
    flock 9 || fail 4 'Cannot lock destination'
fi
stamp=$(date -u +%Y-%m-%d-%H%M%S-%N)
archive="$dest/$prefix$stamp.tar.gz"
archives=()
shopt -s nullglob
for path in "$dest/$prefix"*.tar.gz; do
    suffix=${path#"$dest/$prefix"}
    if [[ -f $path && ! -L $path && $suffix =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}-[0-9]{9}\.tar\.gz$ ]]; then
        archives+=("$path")
    fi
done
# Bash's glob order respects locale; use a bytewise, NUL-safe sort explicitly.
mapfile -d '' -t archives < <(printf '%s\0' "${archives[@]}" "$archive" | LC_ALL=C sort -z)
remove=$((${#archives[@]} - keep))
((remove >= 0)) || remove=0
if "$dry_run"; then
    printf 'CREATE directory %q (if missing)\nCREATE archive %q from %q\n' "$dest" "$archive" "$source_dir"
    for ((i=0; i<remove; i++)); do printf 'DELETE %q\n' "${archives[i]}"; done
    log "result=dry-run archives_planned=1 deleted_planned=$remove"
    exit 0
fi
partial=$(mktemp "$dest/.backup-$identity-XXXXXX.partial") || fail 5 'Cannot create temporary archive'
if ! tar -czf "$partial" -C "$(dirname -- "$source_dir")" -- "$base"; then fail 5 'tar failed; existing backups preserved'; fi
bytes=$(stat -c %s -- "$partial") || fail 5 'Cannot measure archive'
files=$(find "$source_dir" -type f -printf '.' | wc -c) || fail 5 'Cannot count source files'
mv -- "$partial" "$archive" || fail 5 'Cannot publish archive'
partial=''
for ((i=0; i<remove; i++)); do rm -- "${archives[i]}" || fail 6 'Cannot remove old archive'; done
printf 'Created %s\n' "$archive"
log "result=success archived_files=$files archives_created=1 deleted=$remove archive_bytes=$bytes"
