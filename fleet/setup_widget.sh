#!/bin/bash
# Fleet Deck Setup for Termux on Android
# Run this in Termux

echo "=== Fleet Deck Setup ==="
echo ""

# Check if running in Termux
if [ ! -d "/data/data/com.termux/files" ]; then
    echo "❌ This must be run in Termux app"
    exit 1
fi

# Install Python if not present
if ! command -v python3 &> /dev/null; then
    echo "📦 Installing Python..."
    pkg update -y
    pkg install python3 -y
    pkg install pyyaml -y
fi

# Create shortcuts directory
mkdir -p ~/.shortcuts/fleet-deck

# Copy fleet_deck.py
SCRIPT_DIR="$HOME/storage/shared/karma/fleet"
if [ -f "$SCRIPT_DIR/fleet_deck.py" ]; then
    cp "$SCRIPT_DIR/fleet_deck.py" ~/.shortcuts/fleet-deck/
    echo "✅ Copied fleet_deck.py"
else
    echo "❌ fleet_deck.py not found at $SCRIPT_DIR"
    echo "   Copy fleet_deck.py to your phone first"
fi

# Create launcher script
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

echo ""
echo "=== Setup Complete ==="
echo ""
echo "To run Fleet Deck:"
echo "  1. In Termux: cd ~/.shortcuts/fleet-deck && python3 fleet_deck.py"
echo "  2. Or long-press Termux icon -> Shortcuts -> fleet-deck"
echo "  3. Or use Termux:Widget (long-press home screen)"
echo ""
echo "Make sure karma folder is at: ~/storage/shared/karma/"
echo "If not, copy it to your phone first via USB/adb/shares"