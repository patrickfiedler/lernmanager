#!/bin/bash
#
# Lernmanager Deployment Script
#
# Usage:
#   ./deploy/deploy.sh                    # Uses LERNMANAGER_SERVER env var
#   LERNMANAGER_SERVER=user@host ./deploy/deploy.sh
#
# Prerequisites:
#   - SSH key authentication to server
#   - sudo access for systemctl (passwordless recommended for deploy user)
#

set -e

# Configuration
SERVER="${LERNMANAGER_SERVER:-}"
APP_DIR="/opt/lernmanager"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check server is configured
if [ -z "$SERVER" ]; then
    echo -e "${RED}Error: LERNMANAGER_SERVER not set${NC}"
    echo "Usage: LERNMANAGER_SERVER=user@host ./deploy/deploy.sh"
    exit 1
fi

# Check we're on main branch
BRANCH=$(git -C "$LOCAL_DIR" rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" != "main" ]; then
    echo -e "${RED}Error: Not on main branch (currently on '$BRANCH')${NC}"
    echo "Switch to main branch before deploying."
    exit 1
fi

# Check for uncommitted changes
if ! git -C "$LOCAL_DIR" diff-index --quiet HEAD --; then
    echo -e "${YELLOW}Warning: You have uncommitted changes${NC}"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${YELLOW}Deploying Lernmanager to ${SERVER}...${NC}"
echo ""

# Sync files
echo "Syncing files..."
rsync -avz --delete \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='data' \
    --exclude='instance' \
    --exclude='todo.md' \
    --exclude='*.pyc' \
    --exclude='venv' \
    "$LOCAL_DIR/" "$SERVER:$APP_DIR/"

# Fix permissions
echo ""
echo "Fixing permissions..."
ssh "$SERVER" "sudo chown -R lernmanager:lernmanager $APP_DIR && sudo chmod 755 $APP_DIR && sudo chmod -R 755 $APP_DIR/static"

# Update dependencies
echo ""
echo "Updating dependencies..."
ssh "$SERVER" "sudo -u lernmanager $APP_DIR/venv/bin/pip install -q -r $APP_DIR/requirements.txt"

# Restart service
echo ""
echo "Restarting service..."
ssh "$SERVER" "sudo systemctl restart lernmanager"

echo ""
echo -e "${GREEN}Deployment complete!${NC}"
echo ""
echo "Service status:"
ssh "$SERVER" "systemctl status lernmanager --no-pager -l"
