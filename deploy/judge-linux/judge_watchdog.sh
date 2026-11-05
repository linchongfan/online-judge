#!/usr/bin/env bash
set -Eeuo pipefail

WORK_ROOT=${JUDGE_WORK_ROOT:-/var/lib/xinbaoyan-judge/work}
META_ROOT=${JUDGE_META_ROOT:-/var/lib/xinbaoyan-judge/meta}
MAX_AGE_SECONDS=${JUDGE_WATCHDOG_MAX_AGE_SECONDS:-3600}
MAX_WORKER_MEM_MB=${JUDGE_WATCHDOG_MAX_WORKER_MEM_MB:-2048}
SERVICE=${XINBAOYAN_JUDGE_SERVICE:-xinbaoyan-judge-worker.service}

systemctl is-active --quiet "$SERVICE" || systemctl restart "$SERVICE"

worker_main_pid=$(systemctl show -p MainPID --value "$SERVICE")
if [[ $worker_main_pid =~ ^[0-9]+$ && $worker_main_pid -gt 0 ]]; then
    worker_mem_kb=$(awk '/VmRSS:/ {print $2}' "/proc/$worker_main_pid/status" 2>/dev/null || echo 0)
    worker_mem_mb=$((worker_mem_kb / 1024))
    if [[ $worker_mem_mb -gt $MAX_WORKER_MEM_MB ]]; then
        systemctl kill --signal=SIGKILL "$SERVICE"
        systemctl restart "$SERVICE"
    fi
fi

find "$WORK_ROOT" -mindepth 1 -maxdepth 1 -type d -mmin "+$((MAX_AGE_SECONDS / 60))" -exec rm -rf -- {} +
find "$META_ROOT" -mindepth 1 -maxdepth 1 -type d -mmin "+$((MAX_AGE_SECONDS / 60))" -exec rm -rf -- {} +
find /tmp -mindepth 1 -maxdepth 1 -name 'box-*' -mmin "+$((MAX_AGE_SECONDS / 60))" -exec rm -rf -- {} +
