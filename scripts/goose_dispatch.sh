#!/usr/bin/env bash
set -euo pipefail

KARMA_DIR="/home/mikoleye/karma"
PLANNER_DIR="$KARMA_DIR/bridge/planner"
ROLES_DIR="$KARMA_DIR/bridge/roles"
COMMAND_FILE="$PLANNER_DIR/command.md"
SUMMARY_FILE="$PLANNER_DIR/summary.md"
STATE_HASH_FILE="$PLANNER_DIR/.last_command.sha256"
DEBUG_PROMPT_FILE="$PLANNER_DIR/.last_goose_prompt.txt"
DEBUG_RAW_FILE="$PLANNER_DIR/.last_goose_raw.txt"
RENDER_SCRIPT="$KARMA_DIR/scripts/render_summary.py"
GOOSE_BIN="${GOOSE_BIN:-$HOME/.local/bin/goose}"
FORCE_RUN=0

if [[ "${1:-}" == "--force" ]]; then
    FORCE_RUN=1
fi

extract_section() {
    local section="$1"
    awk -v section="$section" '
        $0 == "# " section { in_section=1; next }
        in_section && /^# / { exit }
        in_section { print }
    ' "$COMMAND_FILE" | sed 's/\r$//'
}

render_summary() {
    local status="$1"
    local role="$2"
    local objective="$3"
    local files_in_scope="$4"
    local files_read="$5"
    local files_changed="$6"
    local summary="$7"
    local blockers="$8"
    local next_role="$9"
    local next_step="${10}"
    local raw_file="${11}"
    local commands_run="${12:-}"
    local key_output="${13:-}"

    SUMMARY_STATUS="$status" \
    SUMMARY_ACTIVE_ROLE="$role" \
    SUMMARY_OBJECTIVE="$objective" \
    SUMMARY_FILES_IN_SCOPE="$files_in_scope" \
    SUMMARY_FILES_READ="$files_read" \
    SUMMARY_FILES_CHANGED="$files_changed" \
    SUMMARY_COMMANDS_RUN="$commands_run" \
    SUMMARY_KEY_OUTPUT="$key_output" \
    SUMMARY_TEXT="$summary" \
    SUMMARY_BLOCKERS="$blockers" \
    SUMMARY_NEXT_ROLE="$next_role" \
    SUMMARY_NEXT_STEP="$next_step" \
    python3 "$RENDER_SCRIPT" "$SUMMARY_FILE" < "$raw_file"
}

if [[ ! -f "$COMMAND_FILE" ]]; then
    tmp=$(mktemp)
    printf 'command.md not found\n' > "$tmp"
    render_summary "error" "none" "" "" "" "" "command.md not found" "missing command.md" "planner" "Write bridge/planner/command.md" "$tmp"
    rm -f "$tmp"
    exit 1
fi

NEXT_ROLE="$(extract_section "NEXT ROLE" | sed '/^$/d' | head -n1 | tr '[:upper:]' '[:lower:]')"
OBJECTIVE="$(extract_section "OBJECTIVE" | sed '/^$/d')"
FILES_IN_SCOPE="$(extract_section "FILES IN SCOPE" | sed '/^$/d')"
INSTRUCTIONS_TEXT="$(extract_section "INSTRUCTIONS" | sed '/^$/d')"
SUCCESS_CHECK="$(extract_section "SUCCESS CHECK" | sed '/^$/d')"
IF_BLOCKED="$(extract_section "IF BLOCKED" | sed '/^$/d')"

if [[ -z "$NEXT_ROLE" || -z "$OBJECTIVE" ]]; then
    tmp=$(mktemp)
    printf 'Malformed command.md\n' > "$tmp"
    render_summary "error" "${NEXT_ROLE:-none}" "$OBJECTIVE" "$FILES_IN_SCOPE" "" "" "Malformed command.md" "required headings: # NEXT ROLE and # OBJECTIVE" "planner" "Rewrite bridge/planner/command.md with the required headings" "$tmp"
    rm -f "$tmp"
    exit 1
fi

ROLE_FILE="$ROLES_DIR/$NEXT_ROLE.md"
# Fall back to goose_planner if role not found
if [[ ! -f "$ROLE_FILE" ]]; then
    ROLE_FILE="$ROLES_DIR/goose_planner.md"
fi
if [[ ! -f "$ROLE_FILE" ]]; then
    tmp=$(mktemp)
    printf 'Unknown role: %s\n' "$NEXT_ROLE" > "$tmp"
    render_summary "error" "$NEXT_ROLE" "$OBJECTIVE" "$FILES_IN_SCOPE" "" "" "Unknown role" "missing role file: bridge/roles/$NEXT_ROLE.md" "planner" "Use one of the existing role files under bridge/roles/" "$tmp"
    rm -f "$tmp"
    exit 1
fi

current_hash="$(sha256sum "$COMMAND_FILE" | awk '{print $1}')"
last_hash="$(cat "$STATE_HASH_FILE" 2>/dev/null || true)"
if [[ "$FORCE_RUN" -ne 1 && "$current_hash" == "$last_hash" && -f "$SUMMARY_FILE" ]]; then
    echo "No command change; skipping dispatch."
    exit 0
fi

role_prompt="$(cat "$ROLE_FILE")"

prompt_file="$(mktemp)"
cat > "$prompt_file" <<EOF
You are Goose operating inside the Karma bridge. Start immediately. Do not ask follow-up questions. Do not enter generic chat mode.
You are working in: $KARMA_DIR
Only mention files you actually inspected or verified. If you cannot verify a claim from the repo, mark the task blocked instead of guessing.

Use these role instructions:
$role_prompt

Execute this task now and return only the required report.

NEXT ROLE
$NEXT_ROLE

OBJECTIVE
$OBJECTIVE

FILES IN SCOPE
$FILES_IN_SCOPE

INSTRUCTIONS
$INSTRUCTIONS_TEXT

SUCCESS CHECK
$SUCCESS_CHECK

IF BLOCKED
$IF_BLOCKED

Return ONLY this exact output shape:

## STATUS
<complete|blocked|error>

## SUMMARY
<concise task result>

## FILES READ
- path

## FILES CHANGED
- path

## COMMANDS RUN
- command you executed (if any)

## KEY ERROR OUTPUT
- relevant error lines (if any)

## BLOCKERS
<none or concise blocker list>

## RECOMMENDED NEXT ROLE
<role>

## RECOMMENDED NEXT STEP
<next action>
EOF

cp "$prompt_file" "$DEBUG_PROMPT_FILE"
echo "=== Prompt saved to $DEBUG_PROMPT_FILE ===" >&2

raw_output_file="$(mktemp)"
status="error"
summary_text=""
files_read=""
files_changed=""
blockers_text="none"
next_role="planner"
next_step="Inspect .last_goose_prompt.txt and .last_goose_raw.txt"

echo "=== Running Goose ===" >&2

if ! (cd "$KARMA_DIR" && "$GOOSE_BIN" run --no-session --quiet --max-turns "${GOOSE_MAX_TURNS:-8}" --instructions "$prompt_file") > "$raw_output_file" 2>&1; then
    status="error"
    summary_text="Goose execution failed"
    blockers_text="goose run returned non-zero"
    echo "=== Goose failed ===" >&2
    render_summary "$status" "$NEXT_ROLE" "$OBJECTIVE" "$FILES_IN_SCOPE" "" "" "$summary_text" "$blockers_text" "planner" "Check goose runtime" "$raw_output_file"
    cp "$raw_output_file" "$DEBUG_RAW_FILE"
    rm -f "$prompt_file" "$raw_output_file"
    exit 1
fi

cp "$raw_output_file" "$DEBUG_RAW_FILE"
echo "=== Raw output saved to $DEBUG_RAW_FILE ===" >&2

echo "=== Raw output ===" >&2
cat "$raw_output_file" >&2
echo "=== End raw output ===" >&2

generic_chat_patterns="what would you like me to do|how can i help|what would you like|what should i do|tell me what to do|i'm ready to help|would you like me to continue|^yes[[:space:][:punct:]]"
if grep -iqE "$generic_chat_patterns" "$raw_output_file" 2>/dev/null; then
    tmp=$(mktemp)
    cat > "$tmp" <<EOF
STATUS: error

SUMMARY: Dispatcher prompt handoff failed - Goose entered generic chat mode instead of processing the task

FILES_READ:
- $COMMAND_FILE
- $ROLE_FILE

FILES_CHANGED:
- none

BLOCKERS:
- Goose did not receive the task payload correctly

RECOMMENDED_NEXT_ROLE: planner

RECOMMENDED_NEXT_STEP: Check .last_goose_prompt.txt and .last_goose_raw.txt for debugging
EOF
    echo "=== DETECTED GENERIC CHAT MODE ===" >&2
    render_summary "error" "$NEXT_ROLE" "$OBJECTIVE" "$FILES_IN_SCOPE" "" "" "Dispatcher prompt handoff failed - Goose entered generic chat mode" "Goose did not receive the task payload" "planner" "Check debug files" "$tmp"
    rm -f "$prompt_file" "$raw_output_file" "$tmp"
    exit 1
fi

normalized_output_file="$(mktemp)"
awk '
    BEGIN {
        split("STATUS|SUMMARY|FILES READ|FILES CHANGED|COMMANDS RUN|KEY ERROR OUTPUT|BLOCKERS|RECOMMENDED NEXT ROLE|RECOMMENDED NEXT STEP", arr, "|")
        for (i in arr) expected[arr[i]] = 1
    }
    /^## / {
        heading = substr($0, 4)
        if (!(heading in expected)) {
            if (capture) exit
            next
        }
        capture = 1
        current = heading
        seen[heading] = 1
        print
        next
    }
    capture {
        if (current == "RECOMMENDED NEXT STEP" && ($0 ~ /^Return ONLY this exact output shape:/ || $0 ~ /^Respond with ONLY/)) exit
        print
    }
' "$raw_output_file" > "$normalized_output_file"

awk_output="$(cat "$normalized_output_file")"

extract_markdown_section() {
    local heading="$1"
    printf '%s\n' "$awk_output" | awk -v heading="$heading" '
        $0 == "## " heading { capture=1; next }
        capture && /^## / { exit }
        capture { print }
    ' | sed '/^$/d'
}

parsed_status="$(extract_markdown_section "STATUS" | head -n1 | tr '[:upper:]' '[:lower:]')"
parsed_summary="$(extract_markdown_section "SUMMARY")"
parsed_files_read="$(extract_markdown_section "FILES READ")"
parsed_files_changed="$(extract_markdown_section "FILES CHANGED")"
parsed_blockers="$(extract_markdown_section "BLOCKERS")"
parsed_commands_run="$(extract_markdown_section "COMMANDS RUN")"
parsed_key_output="$(extract_markdown_section "KEY ERROR OUTPUT")"
parsed_next_role="$(extract_markdown_section "RECOMMENDED NEXT ROLE" | head -n1)"
parsed_next_step="$(extract_markdown_section "RECOMMENDED NEXT STEP")"

echo "=== Parsed results ===" >&2
echo "STATUS: $parsed_status" >&2
echo "SUMMARY: $parsed_summary" >&2
echo "FILES_READ: $parsed_files_read" >&2
echo "FILES_CHANGED: $parsed_files_changed" >&2
echo "COMMANDS_RUN: $parsed_commands_run" >&2
echo "KEY_OUTPUT: $parsed_key_output" >&2

if [[ -z "$parsed_status" ]]; then
    status="error"
    summary_text="Dispatcher summary extraction failed"
    blockers_text="STATUS missing from Goose output"
    next_role="planner"
    next_step="Inspect .last_goose_prompt.txt and .last_goose_raw.txt, then rerun forced dispatch"
elif [[ "$parsed_status" != "complete" && "$parsed_status" != "blocked" && "$parsed_status" != "error" ]]; then
    status="error"
    summary_text="Dispatcher summary extraction failed"
    blockers_text="STATUS must be one of: complete, blocked, error"
    next_role="planner"
    next_step="Inspect .last_goose_raw.txt and correct Goose output format"
else
    status="$parsed_status"
fi
[[ -n "$parsed_summary" ]] && summary_text="$parsed_summary"
[[ -n "$parsed_files_read" ]] && files_read="$parsed_files_read"
[[ -n "$parsed_files_changed" ]] && files_changed="$parsed_files_changed"
[[ -n "$parsed_blockers" ]] && blockers_text="$parsed_blockers"
[[ -n "$parsed_next_role" ]] && next_role="$parsed_next_role"
[[ -n "$parsed_next_step" ]] && next_step="$parsed_next_step"

SUMMARY_COMMANDS_RUN="$parsed_commands_run" \
SUMMARY_KEY_OUTPUT="$parsed_key_output" \
render_summary "$status" "$NEXT_ROLE" "$OBJECTIVE" "$FILES_IN_SCOPE" "$files_read" "$files_changed" "$summary_text" "$blockers_text" "$next_role" "$next_step" "$normalized_output_file" "$parsed_commands_run" "$parsed_key_output"
printf '%s\n' "$current_hash" > "$STATE_HASH_FILE"
rm -f "$prompt_file" "$raw_output_file" "$normalized_output_file"
echo "=== Summary written to $SUMMARY_FILE ==="
