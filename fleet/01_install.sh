#!/bin/bash
# Fleet Deck Installer - Run this in Termux to set up everything
# Step 1: Install required packages

echo "=== Fleet Deck Installer ==="
echo ""

# Update package list
echo "📦 Updating packages..."
pkg update -y 2>/dev/null

# Install Python and required packages
echo "🐍 Installing Python..."
pkg install python -y 2>/dev/null || pkg install python3 -y 2>/dev/null
pkg install pyyaml -y 2>/dev/null

# Verify Python
if command -v python3 &> /dev/null; then
    echo "✅ Python installed: $(python3 --version)"
elif command -v python &> /dev/null; then
    echo "✅ Python installed: $(python --version)"
else
    echo "❌ Python not found"
    exit 1
fi

# Install yaml
python3 -c "import yaml" 2>/dev/null || pip3 install pyyaml 2>/dev/null

echo ""
echo "✅ Installation complete!"
echo ""
echo "Now run: python3 /sdcard/karma/fleet/fleet_deck.py"