#!/bin/bash
#
# Lernmanager Initial Server Setup Script
#
# This script performs a complete initial setup of Lernmanager on a fresh server.
# Run this once per server as root or with sudo.
#
# Usage:
#   sudo ./setup.sh
#   curl -sSL https://raw.githubusercontent.com/patrickfiedler/lernmanager/main/deploy/setup.sh | sudo bash
#
# Prerequisites:
#   - Ubuntu/Debian-based system
#   - Root or sudo access
#   - Internet connectivity
#

set -e  # Exit on error
set -o pipefail  # Catch errors in pipes

# Configuration
APP_DIR="/opt/lernmanager"
REPO_URL="https://github.com/patrickfiedler/lernmanager.git"
APP_USER="lernmanager"
SYSTEMD_SERVICE="/etc/systemd/system/lernmanager.service"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

# Helper functions
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${BLUE}=== $1 ===${NC}"; }

# Error trap
trap 'log_error "Script failed at line $LINENO. Exiting."; exit 1' ERR

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root or with sudo"
        echo "Usage: sudo $0"
        exit 1
    fi
}

# Check if command exists
check_command() {
    command -v "$1" &> /dev/null
}

# Main setup function
main() {
    log_step "Lernmanager Initial Server Setup"
    echo "This will install Lernmanager to $APP_DIR"
    echo ""

    # 1. Validate environment
    log_step "Step 1/9: Validating Environment"
    check_root

    # Check OS
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
            log_warn "This script is designed for Ubuntu/Debian. Your OS: $ID"
            read -p "Continue anyway? (y/N) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit 1
            fi
        else
            log_info "OS detected: $ID $VERSION_ID"
        fi
    fi

    # Check if already installed
    if [ -d "$APP_DIR" ]; then
        log_error "Directory $APP_DIR already exists"
        log_error "If you want to update an existing installation, use deploy/deploy.sh instead"
        exit 1
    fi

    # 2. Install system dependencies
    log_step "Step 2/9: Installing System Dependencies"
    log_info "Updating package lists..."
    apt update -qq

    log_info "Installing required packages..."
    apt install -y python3 python3-venv python3-pip git curl > /dev/null

    log_info "Installed versions:"
    python3 --version
    git --version
    pip3 --version

    # 3. Create application user
    log_step "Step 3/9: Creating Application User"
    if id "$APP_USER" &>/dev/null; then
        log_warn "User $APP_USER already exists"
    else
        log_info "Creating system user: $APP_USER"
        useradd -r -s /usr/sbin/nologin -m -d "$APP_DIR" "$APP_USER"
        log_info "User created successfully"
    fi

    # 4. Clone repository
    log_step "Step 4/9: Cloning Repository"
    log_info "Cloning from $REPO_URL..."
    git clone --quiet "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
    git checkout main

    CURRENT_COMMIT=$(git rev-parse --short HEAD)
    log_info "Cloned commit: $CURRENT_COMMIT"

    log_info "Setting ownership to $APP_USER..."
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"

    # 5. Create Python virtual environment
    log_step "Step 5/9: Setting Up Python Environment"
    log_info "Creating virtual environment..."
    sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"

    log_info "Upgrading pip..."
    sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet --upgrade pip

    log_info "Installing Python dependencies..."
    sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
    log_info "Dependencies installed successfully"

    # 6. Create data directories
    log_step "Step 6/9: Creating Data Directories"
    mkdir -p "$APP_DIR/data"
    mkdir -p "$APP_DIR/instance/uploads"
    mkdir -p "$APP_DIR/instance/tmp"

    log_info "Setting ownership and permissions..."
    chown -R "$APP_USER:$APP_USER" "$APP_DIR"
    chmod 755 "$APP_DIR/data"
    chmod 755 "$APP_DIR/instance/uploads"
    chmod 755 "$APP_DIR/instance/tmp"
    log_info "Directories created successfully"

    # 7. Generate secrets
    log_step "Step 7/9: Generating Secrets"
    log_info "Generating SECRET_KEY..."
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

    if [ -z "$SECRET_KEY" ]; then
        log_error "Failed to generate SECRET_KEY"
        exit 1
    fi

    log_info "SECRET_KEY generated (64 characters)"

    # Save secret to file for reference
    SECRET_FILE="$APP_DIR/.secrets"
    echo "SECRET_KEY=$SECRET_KEY" > "$SECRET_FILE"
    echo "Generated on: $(date)" >> "$SECRET_FILE"
    chmod 600 "$SECRET_FILE"
    chown root:root "$SECRET_FILE"
    log_info "Secret saved to $SECRET_FILE (root access only)"

    # 8. Configure systemd service
    log_step "Step 8/9: Configuring Systemd Service"
    log_info "Copying service file..."
    cp "$APP_DIR/deploy/lernmanager.service" "$SYSTEMD_SERVICE"

    log_info "Injecting SECRET_KEY..."
    sed -i "s/CHANGE_ME_TO_RANDOM_STRING/$SECRET_KEY/" "$SYSTEMD_SERVICE"

    log_info "Reloading systemd..."
    systemctl daemon-reload

    log_info "Enabling service..."
    systemctl enable lernmanager

    log_info "Starting service..."
    systemctl start lernmanager

    # Wait for service to start
    sleep 3

    # 9. Verify installation
    log_step "Step 9/9: Verifying Installation"

    if systemctl is-active --quiet lernmanager; then
        log_info "✓ Service is running"
    else
        log_error "✗ Service failed to start"
        log_error "Check logs with: journalctl -u lernmanager -n 50"
        exit 1
    fi

    # Test HTTP endpoint
    log_info "Testing HTTP endpoint..."
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080 || echo "000")

    if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "302" ]]; then
        log_info "✓ Application is responding (HTTP $HTTP_CODE)"
    else
        log_warn "⚠ Unexpected HTTP response: $HTTP_CODE"
        log_warn "Service is running but may not be fully functional"
    fi

    # Print summary
    log_step "Installation Complete!"
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║           Lernmanager Successfully Installed!               ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Installation Details:${NC}"
    echo "  Location:        $APP_DIR"
    echo "  Git commit:      $CURRENT_COMMIT"
    echo "  Service status:  $(systemctl is-active lernmanager)"
    echo "  Local URL:       http://127.0.0.1:8080"
    echo ""
    echo -e "${BLUE}Default Admin Credentials:${NC}"
    echo "  Username:        admin"
    echo "  Password:        admin"
    echo "  ${RED}⚠ IMPORTANT: Change this password immediately after first login!${NC}"
    echo ""
    echo -e "${BLUE}Secrets Stored In:${NC}"
    echo "  File:            $SECRET_FILE"
    echo "  Systemd service: $SYSTEMD_SERVICE"
    echo "  ${YELLOW}Keep these secure! If lost, you'll need to regenerate them.${NC}"
    echo ""
    echo -e "${BLUE}Next Steps:${NC}"
    echo "  1. Configure Nginx as reverse proxy (see deploy/nginx.conf)"
    echo "  2. Set up HTTPS with: sudo certbot --nginx -d YOUR_DOMAIN"
    echo "  3. Configure firewall: sudo ufw allow 'Nginx Full' && sudo ufw enable"
    echo "  4. Login and change admin password"
    echo "  5. For updates, use: sudo $APP_DIR/deploy/update.sh"
    echo ""
    echo -e "${BLUE}Useful Commands:${NC}"
    echo "  View logs:       sudo journalctl -u lernmanager -f"
    echo "  Restart service: sudo systemctl restart lernmanager"
    echo "  Check status:    sudo systemctl status lernmanager"
    echo ""
    echo -e "${GREEN}Documentation: https://github.com/patrickfiedler/lernmanager${NC}"
    echo ""
}

# Run main function
main "$@"
