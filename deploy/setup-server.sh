#!/bin/bash
# ============================================================
# Server setup script for the dYdX trading bot.
#
# Run this ONCE on a fresh Ubuntu server (e.g. DigitalOcean, AWS):
#   curl -sSL https://raw.githubusercontent.com/YOUR_REPO/deploy/setup-server.sh | bash
#
# Or SSH in and run manually:
#   chmod +x deploy/setup-server.sh && ./deploy/setup-server.sh
# ============================================================

set -e

echo "=== dYdX Bot Server Setup ==="

# 1. System packages
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git cmake g++ build-essential

# 2. Clone repo (skip if already present)
REPO_DIR="$HOME/dydx-v3-python"
if [ ! -d "$REPO_DIR" ]; then
    echo "[2/6] Cloning repository..."
    git clone https://github.com/Meril99/dyDXCrpyto.git "$REPO_DIR"
else
    echo "[2/6] Repository already exists, pulling latest..."
    cd "$REPO_DIR" && git pull
fi

cd "$REPO_DIR"

# 3. Python dependencies
echo "[3/6] Installing Python dependencies..."
pip3 install -r requirements.txt

# 4. Build C++ orderbook (optional, skip if cmake fails)
echo "[4/6] Building C++ order book..."
if [ -f cpp/build.sh ]; then
    cd cpp && chmod +x build.sh && ./build.sh && cd ..
    echo "  C++ module built successfully."
else
    echo "  Skipping C++ build (build.sh not found)."
fi

# 5. Set up .env file
echo "[5/6] Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  Created .env from .env.example"
    echo "  >>> IMPORTANT: Edit .env with your API keys! <<<"
    echo "  Run: nano $REPO_DIR/.env"
else
    echo "  .env already exists, skipping."
fi

# 6. Install systemd service
echo "[6/6] Installing systemd service..."
SERVICE_FILE="deploy/dydx-bot.service"

# Replace username in service file
CURRENT_USER=$(whoami)
sed "s/ubuntu/$CURRENT_USER/g" "$SERVICE_FILE" > /tmp/dydx-bot.service
sed -i "s|/home/$CURRENT_USER/dydx-v3-python|$REPO_DIR|g" /tmp/dydx-bot.service

sudo cp /tmp/dydx-bot.service /etc/systemd/system/dydx-bot.service
sudo systemctl daemon-reload
echo "  Service installed."

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit your credentials:  nano $REPO_DIR/.env"
echo "  2. Test the bot manually:  cd $REPO_DIR && PYTHONPATH=. python3 bot.py"
echo "  3. Start as a service:     sudo systemctl start dydx-bot"
echo "  4. Enable auto-start:      sudo systemctl enable dydx-bot"
echo "  5. Check status:           sudo systemctl status dydx-bot"
echo "  6. View logs:              tail -f $REPO_DIR/bot.log"
echo "  7. Stop the bot:           sudo systemctl stop dydx-bot"
echo ""
echo "  TIP: Start with DYDX_HOST=https://api.stage.dydx.exchange (testnet)"
echo "       to test with fake money first!"
