#!/usr/bin/env bash
set -euo pipefail

# OpsLens cluster diagnostics collector
# Produces a tar.gz with useful, parseable outputs.

umask 077

need_cmd() { command -v "$1" >/dev/null 2>&1; }

TIMEOUT_SECS="${TIMEOUT_SECS:-12}"

run_cmd() {
  local out="$1"; shift
  local cmd=("$@")
  {
    echo "### CMD: ${cmd[*]}"
    echo "### TS : $(date -Is)"
    echo
    if need_cmd timeout; then
      timeout "${TIMEOUT_SECS}"s "${cmd[@]}"
    else
      "${cmd[@]}"
    fi
  } >"$out" 2>&1 || true
}

TMP_DIR="$(mktemp -d)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT INT TERM

HOST="$(hostname -s 2>/dev/null || hostname || echo unknown-host)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_NAME="opslens_${HOST}_${TS}.tar.gz"
WORK="$TMP_DIR/$HOST-$TS"
mkdir -p "$WORK"

cat >"$WORK/meta.txt" <<EOF
host=$HOST
timestamp_utc=$TS
generated_at=$(date -Is)
user=$(id -un 2>/dev/null || echo unknown)
EOF

run_cmd "$WORK/uname.txt" uname -a
run_cmd "$WORK/os_release.txt" bash -lc 'test -f /etc/os-release && cat /etc/os-release || true'
run_cmd "$WORK/uptime.txt" uptime
run_cmd "$WORK/df.txt" df -P -T
run_cmd "$WORK/free.txt" free -b
run_cmd "$WORK/top.txt" bash -lc 'top -b -n 1 | head -n 50'

if need_cmd systemctl; then
  run_cmd "$WORK/systemd_running_services.txt" systemctl list-units --type=service --state=running --no-pager
  run_cmd "$WORK/systemd_failed_units.txt" systemctl --failed --no-pager
else
  echo "systemctl not found" >"$WORK/systemd_running_services.txt"
fi

# Logs: prefer journalctl; else syslog tail
if need_cmd journalctl; then
  run_cmd "$WORK/log_tail.txt" journalctl -n 200 --no-pager
elif test -f /var/log/syslog; then
  run_cmd "$WORK/log_tail.txt" bash -lc 'tail -n 200 /var/log/syslog'
elif test -f /var/log/messages; then
  run_cmd "$WORK/log_tail.txt" bash -lc 'tail -n 200 /var/log/messages'
else
  echo "No journalctl/syslog/messages found" >"$WORK/log_tail.txt"
fi

# Optional Kubernetes
if need_cmd kubectl; then
  run_cmd "$WORK/kubectl_version.txt" kubectl version --client --short
  run_cmd "$WORK/k8s_nodes.txt" kubectl get nodes -o wide
  run_cmd "$WORK/k8s_pods.txt" kubectl get pods -A -o wide
else
  echo "kubectl not found" >"$WORK/kubectl_version.txt"
fi

tar -C "$TMP_DIR" -czf "$OUT_NAME" "$(basename "$WORK")"

echo "✅ Created: $OUT_NAME"
echo "Tip: upload it to OpsLens web UI to analyze."
