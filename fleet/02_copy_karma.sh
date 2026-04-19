#!/bin/bash
# Step 2: Copy karma folder to accessible location

echo "=== Copy karma to accessible location ==="
echo ""

# Check if karma exists on internal storage
if [ -d "/sdcard/karma" ]; then
    echo "📁 karma found on internal storage"
    
    # Copy to Termux home storage for easier access
    mkdir -p ~/storage/shared
    cp -r /sdcard/karma ~/storage/shared/
    echo "✅ Copied karma to ~/storage/shared/karma"
else
    echo "❌ karma folder not found on internal storage"
    echo "   Copy karma folder to phone first via USB"
fi

echo ""
echo "Now run: python3 ~/storage/shared/karma/fleet/fleet_deck.py"