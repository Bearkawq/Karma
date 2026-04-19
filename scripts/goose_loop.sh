#!/usr/bin/env bash
set -euo pipefail

KARMA_DIR="/home/mikoleye/karma"
DISPATCH_SCRIPT="$KARMA_DIR/scripts/goose_dispatch.sh"
COMMAND_FILE="$KARMA_DIR/bridge/planner/command.md"
LOOP_DELAY=5

echo "=== Goose Loop Started ==="
echo "PID: $$"
echo "Watching: $COMMAND_FILE"

while true; do
    if [[ ! -x "$DISPATCH_SCRIPT" ]]; then
        echo "ERROR: dispatch script not found or not executable: $DISPATCH_SCRIPT"
        sleep $LOOP_DELAY
        continue
    fi

    if [[ -f "$COMMAND_FILE" ]]; then
        "$DISPATCH_SCRIPT" || true
    fi

    echo "--- Waiting ${LOOP_DELAY}s ---"
    sleep $LOOP_DELAY
done
