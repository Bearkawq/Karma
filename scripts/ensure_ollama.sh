#!/usr/bin/env bash
# Ensure Ollama is running. Call before starting karma.
# Usage: ./scripts/ensure_ollama.sh

OLLAMA_URL="http://localhost:11434/api/tags"
TIMEOUT=30

is_up() {
    curl -sf "$OLLAMA_URL" -o /dev/null 2>/dev/null
}

if is_up; then
    echo "[ollama] already running"
    exit 0
fi

echo "[ollama] not running — starting..."
ollama serve > /tmp/ollama.log 2>&1 &
OLLAMA_PID=$!

elapsed=0
while ! is_up; do
    sleep 1
    elapsed=$((elapsed + 1))
    if [ $elapsed -ge $TIMEOUT ]; then
        echo "[ollama] ERROR: failed to start after ${TIMEOUT}s — check /tmp/ollama.log"
        exit 1
    fi
done

echo "[ollama] up (PID $OLLAMA_PID)"
