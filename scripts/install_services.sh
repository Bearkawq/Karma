#!/bin/bash
# Install systemd services (requires sudo)

echo "Installing systemd services..."

# Copy services to system directory
echo "1021walker" | sudo -S cp /tmp/openclaw-gateway.service /etc/systemd/system/ 2>/dev/null || echo "Could not install openclaw-gateway (permission)"

# Create goose service
cat << 'EOF' | sudo tee /etc/systemd/system/goose.service > /dev/null
[Unit]
Description=Goose AI Agent
After=network-online.target

[Service]
Type=simple
User=mikoleye
WorkingDirectory=/home/mikoleye
ExecStart=/home/mikoleye/.local/bin/goose serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Reload systemd
echo "1021walker" | sudo -S systemctl daemon-reload 2>/dev/null || echo "Could not reload systemd"

echo "Services created. To enable:"
echo "  sudo systemctl enable ollama"
echo "  sudo systemctl enable openclaw-gateway"
echo "  sudo systemctl enable goose"