#!/bin/bash
# Little Gemma - Phone Command Center (Pure Shell Implementation)
# Works without Python - uses toybox commands available on Android
# This is the fallback mode: command-center wrapper, not local model

SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null || true)"
# Default paths for phone storage
ROLE_FILE="${SCRIPT_DIR:-/storage/self/primary/karma/gemma/little_gemma}/role.txt"
MEMORY_FILE="${SCRIPT_DIR:-/storage/self/primary/karma/gemma/little_gemma}/memory.txt"
BRIDGE_INBOX="/storage/self/primary/karma/bridge/inbox"
BRIDGE_OUTBOX="/storage/self/primary/karma/bridge/outbox"

# Load role from file
load_role() {
    if [ -f "$ROLE_FILE" ]; then
        cat "$ROLE_FILE"
    else
        echo "ERROR: role.txt not found at $ROLE_FILE"
    fi
}

# Load memory from file  
load_memory() {
    if [ -f "$MEMORY_FILE" ]; then
        cat "$MEMORY_FILE"
    else
        echo "ERROR: memory.txt not found at $MEMORY_FILE"
    fi
}

# Show status
cmd_status() {
    echo "=== Little Gemma Status ==="
    echo "Role file: $ROLE_FILE"
    if [ -f "$ROLE_FILE" ]; then
        echo "  Status: EXISTS ($(wc -c < $ROLE_FILE) bytes)"
    else
        echo "  Status: MISSING"
    fi
    echo "Memory file: $MEMORY_FILE"
    if [ -f "$MEMORY_FILE" ]; then
        echo "  Status: EXISTS ($(wc -c < $MEMORY_FILE) bytes)"
    else
        echo "  Status: MISSING"
    fi
    echo ""
    echo "Bridge inbox: $BRIDGE_INBOX"
    if [ -d "$BRIDGE_INBOX" ]; then
        COUNT=$(ls $BRIDGE_INBOX/*.json 2>/dev/null | wc -l)
        echo "  Files: $COUNT"
    else
        echo "  Status: NOT FOUND"
    fi
    echo ""
    echo "Bridge outbox: $BRIDGE_OUTBOX"
    if [ -d "$BRIDGE_OUTBOX" ]; then
        COUNT=$(ls $BRIDGE_OUTBOX/*.json 2>/dev/null | wc -l)
        echo "  Files: $COUNT"
    else
        echo "  Status: NOT FOUND"
    fi
}

# Show role
cmd_role() {
    load_role
}

# Show memory
cmd_memory() {
    load_memory
}

# Show identity (behavioral test)
cmd_identity() {
    ROLE=$(load_role)
    if echo "$ROLE" | grep -q "command-center"; then
        echo "VERIFIED: I am little Gemma, phone-side command-center assistant"
    else
        echo "ERROR: Role not properly loaded"
    fi
}

# Create escalation
cmd_escalate() {
    local TASK="$1"
    local CONTEXT="$2" 
    local PRIORITY="${3:-medium}"
    
    if [ -z "$TASK" ]; then
        echo "Usage: little_gemma escalate 'task description' 'context' [priority]"
        return 1
    fi
    
    # Ensure inbox exists
    mkdir -p "$BRIDGE_INBOX"
    
    local TIMESTAMP=$(date +%Y%m%d_%H%M%S)
    local ESCALATION_FILE="$BRIDGE_INBOX/escalation_${TIMESTAMP}.json"
    
    cat > "$ESCALATION_FILE" << EOF
{
  "from": "little_gemma",
  "to": "big_gemma",
  "task": "$TASK",
  "context": "$CONTEXT",
  "priority": "$PRIORITY",
  "timestamp": "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S)"
}
EOF
    
    echo "Escalation created: $ESCALATION_FILE"
}

# Initialize
cmd_init() {
    echo "=== Little Gemma Init ==="
    mkdir -p "$BRIDGE_INBOX" "$BRIDGE_OUTBOX"
    echo "Bridge: /storage/self/primary/karma/bridge/"
    echo "Inbox: $BRIDGE_INBOX"
    echo "Outbox: $BRIDGE_OUTBOX"
    echo ""
    echo "Role file: $ROLE_FILE"
    echo "Memory file: $MEMORY_FILE"
    echo ""
    echo "Initialization complete."
}

# Main
case "${1:-status}" in
    init)     cmd_init ;;
    role)     cmd_role ;;
    memory)   cmd_memory ;;
    status)   cmd_status ;;
    identity) cmd_identity ;;
    escalate) shift; cmd_escalate "$@" ;;
    *)
        echo "Little Gemma - Phone Command Center (Fallback Mode)"
        echo ""
        echo "Usage: $0 [init|role|memory|status|identity|escalate]"
        echo ""
        echo "Commands:"
        echo "  init       - Initialize bridge directories"
        echo "  role       - Display role prompt"
        echo "  memory     - Display memory"
        echo "  status     - Show system status"
        echo "  identity   - Verify identity (behavioral test)"
        echo "  escalate   - Create escalation to STG"
        echo ""
        echo "NOTE: This is the fallback mode - command-center wrapper."
        echo "      No local model running - escalation to STG for deep reasoning."
        ;;
esac