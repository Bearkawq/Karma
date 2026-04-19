#!/usr/bin/env bash
set -euo pipefail

SUMMARY_FILE="/home/mikoleye/karma/bridge/planner/summary.md"
POLL_INTERVAL="${BRIDGE_POLL_INTERVAL:-2}"

echo "Bridge Watcher started - polling every ${POLL_INTERVAL}s"
echo "Watching: $SUMMARY_FILE"

prev_hash=""

while true; do
    if [[ -f "$SUMMARY_FILE" ]]; then
        current_hash="$(sha256sum "$SUMMARY_FILE" | awk '{print $1}')"
        if [[ "$current_hash" != "$prev_hash" ]]; then
            echo "$(date '+%Y-%m-%dT%H:%M:%SZ') - summary.md changed"
            prev_hash="$current_hash"
        fi
    fi

    sleep "$POLL_INTERVAL"
done
