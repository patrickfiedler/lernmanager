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
SERVER="${LERNMANAGER_SERVER:-user@example.de}"
APP_DIR="/opt/lernmanager"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Deploying Lernmanager to ${SERVER}...${NC}"
echo ""

# Pull latest code and restart service
echo "Pulling latest code from main branch..."
ssh "$SERVER" "cd $APP_DIR && git pull origin main"

echo ""
echo "Restarting service..."
ssh "$SERVER" "sudo systemctl restart lernmanager"

echo ""
echo -e "${GREEN}Deployment complete!${NC}"
echo ""
echo "Service status:"
ssh "$SERVER" "systemctl status lernmanager --no-pager -l"
