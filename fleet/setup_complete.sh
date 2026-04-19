#!/bin/bash
# Fleet Deck Complete Setup - Run this in Termux
# Does everything: install Python, copy karma, create shortcuts

set -e

echo "=== Fleet Deck Complete Setup ==="
echo ""

# Step 1: Install packages
echo "📦 Installing packages..."
pkg update -y -qq
pkg install -y -qq python python-yq 2>/dev/null || pkg install -y -qq python3 python3-yaml 2>/dev/null || true
pip3 install pyyaml -q 2>/dev/null || true

echo "✅ Python ready"

# Step 2: Copy karma if needed
KARMA_SRC="/sdcard/karma"
KARMA_DEST="$HOME/storage/shared/karma"

if [ -d "$KARMA_SRC" ]; then
    echo "📁 Copying karma to Termux storage..."
    mkdir -p "$HOME/storage/shared"
    rm -rf "$KARMA_DEST"
    cp -r "$KARMA_SRC" "$KARMA_DEST"
    echo "✅ karma copied to $KARMA_DEST"
elif [ -d "$KARMA_DEST" ]; then
    echo "✅ karma already in place"
else
    echo "⚠️  karma not found. Copy to /sdcard/karma via USB first"
fi

# Step 3: Create shortcuts
echo "🔗 Creating shortcuts..."
mkdir -p ~/.shortcuts/fleet-deck

SCRIPT_DIR="$KARMA_DEST/fleet"
if [ -f "$SCRIPT_DIR/fleet_deck.py" ]; then
    cp "$SCRIPT_DIR/fleet_deck.py" ~/.shortcuts/fleet-deck/
    
    # Create run script
    cat > ~/.shortcuts/fleet-deck/run.sh << 'EOF'
#!/bin/bash
cd ~/.shortcuts/fleet-deck
python3 fleet_deck.py
EOF
    chmod +x ~/.shortcuts/fleet-deck/run.sh
    
    # Create Termux shortcut
    mkdir -p ~/.shortcut
    cat > ~/.shortcut/fleet-deck << 'EOF'
#!/bin/bash
cd ~/.shortcuts/fleet-deck
python3 fleet_deck.py
EOF
    chmod +x ~/.shortcut/fleet-deck
    
    echo "✅ Shortcuts created"
else
    echo "⚠️  fleet_deck.py not found"
fi

# Step 4: Test run
echo ""
echo "=== Running Fleet Deck Test ==="
echo ""

if [ -f "$HOME/storage/shared/karma/fleet/fleet_deck.py" ]; then
    cd $HOME/storage/shared/karma/fleet
    python3 fleet_deck.py << 'TESTEOF'
c
k
t
2
c
q
TESTEOF
else
    echo "❌ Cannot test - file not found"
fi