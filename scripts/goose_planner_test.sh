#!/usr/bin/env bash
# goose_planner_test.sh - Test Goose as primary planner

KARMA_DIR="/home/mikoleye/karma"
PLANNER_DIR="$KARMA_DIR/bridge/planner"
COMMAND_FILE="$PLANNER_DIR/command.md"
GOOSE_BIN="$HOME/.local/bin/goose"

# Create test command
cat > "$COMMAND_FILE" << 'EOF'
# NEXT ROLE
goose_planner

# OBJECTIVE
Verify Goose routing policy is working

# FILES IN SCOPE
bridge/roles/goose_planner.md

# INSTRUCTIONS
Test the routing policy by selecting the correct worker for each task:
1. A complex debugging problem requiring deep analysis
2. A code implementation task
3. A system config inspection task

For each, assign to the correct worker and output the assignment.

# SUCCESS CHECK
All three tasks assigned to correct workers

# IF BLOCKED
Report which part is blocked
EOF

echo "=== Test command written to $COMMAND_FILE ==="
echo ""
cat "$COMMAND_FILE"
echo ""

# Run Goose
echo "=== Running Goose ==="
cd "$KARMA_DIR"
$GOOSE_BIN run --no-session --quiet --max-turns 8 --instructions "$PLANNER_DIR/../roles/goose_planner.md" 2>&1 | tee /tmp/goose_test_output.txt

echo ""
echo "=== Test Complete ==="