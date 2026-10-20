#!/usr/bin/env bash
set -euo pipefail

log_file=${MONITOR_LOG:-monitor.log}
config="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config/monitor.env"
log() {
    local line
    printf -v line '%s action=system_monitor %s' "$(date -u +%FT%TZ)" "$*"
    printf '%s\n' "$line"
    printf '%s\n' "$line" >> "$log_file" || { printf 'Cannot write monitor log\n' >&2; exit 3; }
}
# Called indirectly by the EXIT trap.
# shellcheck disable=SC2329
finish() {
    local rc=$?
    trap - EXIT
    log "result=finished exit_code=$rc"
    exit "$rc"
}
trap 'finish' EXIT
fail() { log "result=error message=$2"; exit "$1"; }
while (($#)); do
    case "$1" in
        --help)
            cat <<'HELP'
Sample Linux CPU, memory, disk space and configured processes/systemd services.
Usage: monitor.sh [--config FILE] [--help]
  --config FILE  Trusted shell config (default: config/monitor.env beside script)
  --help         Show help
Environment overrides: CPU_MAX, MEM_MAX (max used %, 0..100), DISK_MIN_FREE
(min free %, 0..100), DISK_PATHS, PROCESSES, SERVICES (newline-separated lists),
SAMPLE_SECONDS (positive seconds), MONITOR_LOG (default: ./monitor.log).
Example: MEM_MAX=0 ./lab-03/monitor.sh --config lab-03/config/monitor.env
Exit: 0 healthy; 1 alert; 2 arguments/config; 3 OS, sampling or log error.
HELP
            exit 0;;
        --config)
            (($# >= 2)) && [[ $2 != --* ]] || fail 2 'Missing --config value'
            config=$2; shift 2;;
        *) fail 2 "Unknown argument: $1";;
    esac
done
[[ -r $config && -f $config ]] || fail 2 'Config must be a readable file'
# The configuration is trusted shell syntax, like a user-maintained profile.
# shellcheck source=/dev/null
source "$config"
for key in CPU_MAX MEM_MAX DISK_MIN_FREE; do
    value=${!key:-}
    [[ $value =~ ^[0-9]{1,3}([.][0-9]+)?$ ]] || fail 2 "$key must be a percentage"
    awk -v n="$value" 'BEGIN {exit !(n >= 0 && n <= 100)}' || fail 2 "$key must be 0..100"
done
[[ ${SAMPLE_SECONDS:-} =~ ^[0-9]+([.][0-9]+)?$ ]] || fail 2 'SAMPLE_SECONDS must be positive'
awk -v n="$SAMPLE_SECONDS" 'BEGIN {exit !(n > 0 && n <= 60)}' || fail 2 'SAMPLE_SECONDS must be in (0,60]'
[[ -n ${DISK_PATHS:-} ]] || fail 2 'DISK_PATHS must not be empty'
[[ -r /proc/stat && -r /proc/meminfo ]] || fail 3 'Linux procfs required'
read_cpu() { awk '/^cpu / {for(i=2;i<=9;i++) total+=$i; printf "%.0f %.0f\n", total, $5+$6; exit}' /proc/stat; }
read -r total1 idle1 < <(read_cpu)
sleep "$SAMPLE_SECONDS"
read -r total2 idle2 < <(read_cpu)
((total2 > total1)) || fail 3 'No CPU sampling interval available'
cpu=$(awk -v t="$((total2-total1))" -v idle="$((idle2-idle1))" 'BEGIN {printf "%.2f", 100*(t-idle)/t}')
memory=$(awk '/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2} END {if(t<=0 || a<=0) exit 1; printf "%.2f",100*(t-a)/t}' /proc/meminfo) || fail 3 'Cannot sample memory'
alert=0
check_max() {
    local metric=$1 value=$2 limit=$3
    if awk -v v="$value" -v n="$limit" 'BEGIN {exit !(v>n)}'; then
        log "metric=$metric value=$value max=$limit result=ALERT"; alert=1
    else log "metric=$metric value=$value max=$limit result=OK"; fi
}
check_max cpu_used_pct "$cpu" "$CPU_MAX"
check_max memory_used_pct "$memory" "$MEM_MAX"
while IFS= read -r path; do
    [[ -n $path ]] || continue
    usage=$(df -P -- "$path") || fail 3 "Cannot inspect disk: $path"
    free=$(awk 'END {gsub(/%/,"",$(NF-1)); print 100-$(NF-1)}' <<< "$usage")
    printf -v quoted_path '%q' "$path"
    if awk -v v="$free" -v n="$DISK_MIN_FREE" 'BEGIN {exit !(v<n)}'; then
        log "metric=disk_free_pct path=$quoted_path value=$free min=$DISK_MIN_FREE result=ALERT"; alert=1
    else log "metric=disk_free_pct path=$quoted_path value=$free min=$DISK_MIN_FREE result=OK"; fi
done <<< "$DISK_PATHS"
while IFS= read -r name; do
    [[ -n $name ]] || continue
    [[ $name =~ ^[a-zA-Z0-9_.@-]+$ && $name != -* ]] || fail 2 'Invalid service name'
    command -v systemctl >/dev/null || fail 3 'systemctl is required for SERVICES'
    if systemctl is-active --quiet -- "$name"; then log "service=$name result=OK"
    else log "service=$name result=ALERT"; alert=1; fi
done <<< "${SERVICES:-}"
while IFS= read -r name; do
    [[ -n $name ]] || continue
    [[ $name =~ ^[a-zA-Z0-9_.-]+$ && $name != -* ]] || fail 2 'Invalid process name'
    command -v pgrep >/dev/null || fail 3 'pgrep is required for PROCESSES'
    # Names are literals, not regexes (escape the permitted metacharacter dot).
    pattern=${name//./\\.}
    if pgrep -x -- "$pattern" >/dev/null; then log "process=$name result=OK"
    else log "process=$name result=ALERT"; alert=1; fi
done <<< "${PROCESSES:-}"
exit "$alert"
