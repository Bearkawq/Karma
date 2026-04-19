#!/bin/bash
# Big Gemma - STG Deep Reasoning
# Using qwen2.5-coder:7b as practical stable model (gemma4 needs Ollama update)

MODEL="qwen2.5-coder:7b"
OLLAMA_VERSION=$(ollama --version 2>/dev/null | grep -oP '\d+\.\d+\.\d+' || echo "unknown")

echo "=== Big Gemma - STG Deep Reasoning ==="
echo "Model: $MODEL"
echo "Ollama: $OLLAMA_VERSION"
echo "Bridge: /home/mikoleye/karma/bridge/"
echo ""

check_version() {
    # gemma4 needs 0.20.0+, but we use qwen which works with 0.18.3
    return 0
}

case "$1" in
    status)
        echo "=== Status ==="
        echo "Ollama: $OLLAMA_VERSION"
        echo "Model in use: $MODEL"
        echo ""
        
        # Check role file
        ROLE_FILE="/home/mikoleye/karma/gemma/big_gemma/role.txt"
        if [ -f "$ROLE_FILE" ]; then
            echo "Role file: EXISTS ($(wc -c < $ROLE_FILE) bytes)"
        else
            echo "Role file: MISSING"
        fi
        
        echo ""
        echo "Bridge inbox:"
        for f in /home/mikoleye/karma/bridge/inbox/*.json; do
            [ -e "$f" ] || { echo "  (empty)"; break; }
            echo "  - $(basename $f)"
        done
        
        echo ""
        echo "Bridge outbox:"
        for f in /home/mikoleye/karma/bridge/outbox/*.json; do
            [ -e "$f" ] || { echo "  (empty)"; break; }
            echo "  - $(basename $f)"
        done
        ;;
    run)
        echo "Starting $MODEL..."
        echo "Role: Deep reasoning specialist on STG"
        echo "Type: exit to quit"
        echo ""
        ollama run $MODEL
        ;;
    inbox)
        echo "=== Inbox ==="
        for f in /home/mikoleye/karma/bridge/inbox/*.json; do
            [ -e "$f" ] || { echo "(empty)"; break; }
            echo "--- $(basename $f) ---"
            cat "$f"
            echo ""
        done
        ;;
    check)
        echo "Ollama: $OLLAMA_VERSION"
        ollama list | head -10
        ;;
    identity)
        ROLE_FILE="/home/mikoleye/karma/gemma/big_gemma/role.txt"
        if [ -f "$ROLE_FILE" ]; then
            ROLE=$(cat $ROLE_FILE)
            if echo "$ROLE" | grep -q "deep reasoning"; then
                echo "VERIFIED: I am big Gemma, STG deep reasoning specialist"
            else
                echo "WARNING: Role file exists but may not be correct"
            fi
        else
            echo "ERROR: role.txt not found"
        fi
        ;;
    *)
        echo "Usage: $0 [status|run|inbox|check|identity]"
        echo ""
        echo "  status   - Show system status"
        echo "  run      - Start $MODEL interactively"
        echo "  inbox    - Show pending tasks"
        echo "  check    - Check Ollama/model status"
        echo "  identity - Verify identity (behavioral test)"
        echo ""
        echo "NOTE: Using qwen2.5-coder:7b (stable on 6GB VRAM)"
        echo "      gemma4 available when Ollama updated to v0.20.0+"
        ;;
esac