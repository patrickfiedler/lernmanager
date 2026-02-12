#!/bin/bash
#
# Lernmanager Update Script
#
# This script updates an existing Lernmanager installation by pulling
# the latest code from GitHub and restarting the service. It automatically
# rolls back if the service fails to start.
#
# Usage:
#   sudo ./update.sh                          # Run locally on server
#   ssh user@server 'sudo /opt/lernmanager/deploy/update.sh'  # Run remotely
#
# Prerequisites:
#   - Lernmanager already installed (run deploy/setup.sh first)
#   - Root or sudo access
#   - Internet connectivity
#

set -e  # Exit on error
set -o pipefail  # Catch errors in pipes

# Configuration
APP_DIR="/opt/lernmanager"
APP_USER="lernmanager"
SYSTEMD_SERVICE="/etc/systemd/system/lernmanager.service"
BRANCH="main"

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

# Variables for rollback and tracking
CURRENT_COMMIT=""
NEW_COMMIT=""
DEPS_UPDATED=false
SERVICE_UPDATED=false
MIGRATIONS_RUN=false

# Check if running as root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "This script must be run as root or with sudo"
        echo "Usage: sudo $0"
        exit 1
    fi
}

# Rollback function
rollback() {
    log_error "Deployment failed, initiating rollback..."

    cd "$APP_DIR"

    # Rollback git
    log_info "Reverting to commit $CURRENT_COMMIT..."
    sudo -u "$APP_USER" git reset --hard "$CURRENT_COMMIT"

    # Rollback dependencies if they were updated
    if [ "$DEPS_UPDATED" = true ]; then
        log_info "Restoring previous dependencies..."
        sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
    fi

    # Rollback systemd service if it was updated
    if [ "$SERVICE_UPDATED" = true ]; then
        log_info "Restoring previous systemd service..."
        sudo -u "$APP_USER" git show "$CURRENT_COMMIT:deploy/lernmanager.service" > /tmp/lernmanager.service.rollback

        # No need to preserve secrets - they're in .env file!
        cp /tmp/lernmanager.service.rollback "$SYSTEMD_SERVICE"
        rm /tmp/lernmanager.service.rollback
        systemctl daemon-reload
    fi

    # Restart service
    log_info "Restarting service..."
    systemctl restart lernmanager
    sleep 3

    # Verify rollback
    if systemctl is-active --quiet lernmanager; then
        log_info "✓ Rollback successful, service is running"
        log_info "Current commit: $(git rev-parse --short HEAD)"
        exit 1
    else
        log_error "✗ CRITICAL: Rollback failed, service still not starting"
        log_error "Manual intervention required"
        log_error "View logs: journalctl -u lernmanager -n 50"
        exit 2
    fi
}

# Set trap for errors
trap 'rollback' ERR

# Main deployment function
main() {
    log_step "Lernmanager Deployment"

    # 0. Self-update check (before anything else)
    log_step "Step 0/8: Checking for update.sh changes"
    check_root

    if [ ! -d "$APP_DIR" ]; then
        log_error "Directory $APP_DIR does not exist"
        log_error "Run deploy/setup.sh first to perform initial installation"
        exit 1
    fi

    if [ ! -d "$APP_DIR/.git" ]; then
        log_error "$APP_DIR is not a git repository"
        exit 1
    fi

    cd "$APP_DIR"

    # Fetch latest changes
    sudo -u "$APP_USER" git fetch origin main

    # Check if update.sh has changed (skip if we already self-updated)
    if [ "${SELF_UPDATED:-}" != "1" ] && ! sudo -u "$APP_USER" git diff --quiet HEAD origin/main -- deploy/update.sh; then
        log_warn "update.sh has been modified in the new version"
        log_info "Updating update.sh and re-executing..."

        # Pull the latest version
        sudo -u "$APP_USER" git checkout origin/main -- deploy/update.sh

        # Make it executable
        chmod +x "$APP_DIR/deploy/update.sh"

        log_info "Restarting with updated update.sh..."
        exec env SELF_UPDATED=1 "$APP_DIR/deploy/update.sh" "$@"
    fi

    log_info "update.sh is up to date"

    # 1. Validate environment
    log_step "Step 1/8: Validating Environment"

    if [ ! -f "$SYSTEMD_SERVICE" ]; then
        log_error "Systemd service file not found at $SYSTEMD_SERVICE"
        log_error "Run deploy/setup.sh first to perform initial installation"
        exit 1
    fi

    # Verify service is known to systemd
    if ! systemctl list-units --all --full | grep -q "lernmanager.service"; then
        log_warn "Service file exists but may need systemctl daemon-reload"
        systemctl daemon-reload
    fi

    log_info "Environment validated successfully"

    # 2. Pre-deployment snapshot
    log_step "Step 2/8: Creating Pre-Deployment Snapshot"
    cd "$APP_DIR"

    # Get current commit
    CURRENT_COMMIT=$(sudo -u "$APP_USER" git rev-parse HEAD)
    CURRENT_COMMIT_SHORT=$(sudo -u "$APP_USER" git rev-parse --short HEAD)
    log_info "Current commit: $CURRENT_COMMIT_SHORT"

    # Check for local changes
    if ! sudo -u "$APP_USER" git diff --quiet; then
        log_warn "Local changes detected in working directory"
        sudo -u "$APP_USER" git status --short
        log_warn "These will be discarded"
    fi

    # 3. Pull latest code
    log_step "Step 3/8: Pulling Latest Code"

    # Fix git ownership issue (required when running with sudo)
    log_info "Configuring git safe directory..."
    if ! git config --global --get-all safe.directory | grep -q "^$APP_DIR$"; then
        git config --global --add safe.directory "$APP_DIR"
        log_info "Added $APP_DIR to git safe.directory"
    fi

    # Verify repository ownership and permissions
    log_info "Verifying repository ownership..."
    REPO_OWNER=$(stat -c '%U' "$APP_DIR/.git")
    if [ "$REPO_OWNER" != "$APP_USER" ]; then
        log_error "Repository ownership mismatch:"
        log_error "  Expected owner: $APP_USER"
        log_error "  Actual owner:   $REPO_OWNER"
        log_error "  Repository:     $APP_DIR/.git"
        log_error ""
        log_error "Fix with: sudo chown -R $APP_USER:$APP_USER $APP_DIR"
        exit 1
    fi

    log_info "Fetching from origin/$BRANCH..."
    if ! sudo -u "$APP_USER" git fetch origin "$BRANCH" 2>&1 | tee /tmp/git_fetch.log; then
        log_error "Git fetch failed. Output:"
        cat /tmp/git_fetch.log
        rm -f /tmp/git_fetch.log
        exit 1
    fi
    rm -f /tmp/git_fetch.log

    log_info "Resetting to origin/$BRANCH..."
    if ! sudo -u "$APP_USER" git reset --hard "origin/$BRANCH" 2>&1 | tee /tmp/git_reset.log; then
        log_error "Git reset failed. Output:"
        cat /tmp/git_reset.log
        rm -f /tmp/git_reset.log
        exit 1
    fi
    rm -f /tmp/git_reset.log

    NEW_COMMIT=$(sudo -u "$APP_USER" git rev-parse HEAD)
    NEW_COMMIT_SHORT=$(sudo -u "$APP_USER" git rev-parse --short HEAD)

    if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
        log_info "Already up to date at commit $CURRENT_COMMIT_SHORT"
        log_info "No deployment needed"
        exit 0
    fi

    log_info "Updated to commit: $NEW_COMMIT_SHORT"
    echo ""
    log_info "Changes in this deployment:"
    git log --oneline "$CURRENT_COMMIT..$NEW_COMMIT"
    echo ""

    # 4. Update dependencies if requirements.txt changed
    log_step "Step 4/8: Checking Dependencies"
    if git diff --name-only "$CURRENT_COMMIT" "$NEW_COMMIT" | grep -q "^requirements.txt$"; then
        log_info "requirements.txt changed, updating dependencies..."
        sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
        DEPS_UPDATED=true
        log_info "Dependencies updated successfully"
    else
        log_info "No changes to requirements.txt"
    fi

    # 5. Update systemd service if changed
    log_step "Step 5/8: Checking Systemd Service"
    if git diff --name-only "$CURRENT_COMMIT" "$NEW_COMMIT" | grep -q "^deploy/lernmanager.service$"; then
        log_info "Systemd service file changed, updating..."

        # Copy new service file (secrets are in .env, not in service file)
        cp "$APP_DIR/deploy/lernmanager.service" "$SYSTEMD_SERVICE"

        systemctl daemon-reload
        SERVICE_UPDATED=true
        log_info "Systemd service updated successfully"
    else
        log_info "No changes to systemd service"
    fi

    # 6. Run database migrations if needed
    log_step "Step 6/8: Checking Database Migrations"

    # Track completed migrations in a simple text file (one filename per line)
    MIGRATIONS_DONE_FILE="$APP_DIR/data/migrations_done.txt"
    touch "$MIGRATIONS_DONE_FILE"
    chown "$APP_USER:$APP_USER" "$MIGRATIONS_DONE_FILE"

    # Find migration scripts not yet recorded as done
    PENDING_MIGRATIONS=()
    for migration in "$APP_DIR"/migrate_*.py; do
        if [ -f "$migration" ]; then
            MIGRATION_NAME=$(basename "$migration")
            if ! grep -qxF "$MIGRATION_NAME" "$MIGRATIONS_DONE_FILE"; then
                PENDING_MIGRATIONS+=("$migration")
            fi
        fi
    done

    if [ ${#PENDING_MIGRATIONS[@]} -gt 0 ]; then
        log_info "${#PENDING_MIGRATIONS[@]} pending migration(s) found"
        echo ""
        MIGRATIONS_RUN=true

        # Load SQLCIPHER_KEY if it exists in .env (for encrypted databases)
        SQLCIPHER_KEY=""
        if [ -f "$APP_DIR/.env" ] && grep -q "^SQLCIPHER_KEY=" "$APP_DIR/.env"; then
            SQLCIPHER_KEY=$(grep "^SQLCIPHER_KEY=" "$APP_DIR/.env" | cut -d '=' -f2- | tr -d '"' | tr -d "'")
            log_info "SQLCIPHER_KEY loaded from $APP_DIR/.env"
        else
            log_warn "No SQLCIPHER_KEY found in $APP_DIR/.env - database assumed unencrypted"
        fi

        # Run only pending migrations
        MIGRATION_ERRORS=0
        for migration in "${PENDING_MIGRATIONS[@]}"; do
            MIGRATION_NAME=$(basename "$migration")
            log_info "Executing: $MIGRATION_NAME"

            # Run migration as lernmanager user, passing SQLCIPHER_KEY if set
            if [ -n "$SQLCIPHER_KEY" ]; then
                MIGRATION_CMD="sudo -u $APP_USER SQLCIPHER_KEY=\"$SQLCIPHER_KEY\" $APP_DIR/venv/bin/python $migration"
            else
                MIGRATION_CMD="sudo -u $APP_USER $APP_DIR/venv/bin/python $migration"
            fi

            if eval "$MIGRATION_CMD"; then
                log_info "✓ $MIGRATION_NAME completed"
                echo "$MIGRATION_NAME" >> "$MIGRATIONS_DONE_FILE"
            else
                log_error "✗ $MIGRATION_NAME failed"
                MIGRATION_ERRORS=$((MIGRATION_ERRORS + 1))
            fi
            echo ""
        done

        # Clear SQLCIPHER_KEY for security
        SQLCIPHER_KEY=""

        if [ $MIGRATION_ERRORS -gt 0 ]; then
            log_error "$MIGRATION_ERRORS migration(s) failed"
            log_error "Check the output above for details"
            log_error "You may need to run migrations manually"
        else
            log_info "All migrations completed successfully"
        fi
    else
        log_info "No pending migrations"
    fi

    # 7. Restart service
    log_step "Step 7/8: Restarting Service"
    log_info "Restarting lernmanager service..."
    systemctl restart lernmanager

    log_info "Waiting for service to start..."
    sleep 3

    # 8. Verify deployment
    log_step "Step 8/8: Verifying Deployment"

    if systemctl is-active --quiet lernmanager; then
        log_info "✓ Service is active"
    else
        log_error "✗ Service failed to start"
        log_error "Triggering rollback..."
        rollback
    fi

    # Disable error trap now that deployment succeeded
    trap - ERR

    # Print summary
    log_step "Deployment Successful!"
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║         Lernmanager Successfully Updated!                   ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Deployment Details:${NC}"
    echo "  Previous commit:  $CURRENT_COMMIT_SHORT"
    echo "  New commit:       $NEW_COMMIT_SHORT"
    echo "  Dependencies:     $([ "$DEPS_UPDATED" = true ] && echo "Updated" || echo "No changes")"
    echo "  Service file:     $([ "$SERVICE_UPDATED" = true ] && echo "Updated" || echo "No changes")"
    echo "  Migrations:       $([ "$MIGRATIONS_RUN" = true ] && echo "Executed" || echo "None needed")"
    echo "  Service status:   $(systemctl is-active lernmanager)"
    echo ""
    echo -e "${BLUE}Useful Commands:${NC}"
    echo "  View logs:        sudo journalctl -u lernmanager -f"
    echo "  Check status:     sudo systemctl status lernmanager"
    echo "  Manual rollback:  cd $APP_DIR && sudo -u $APP_USER git reset --hard $CURRENT_COMMIT_SHORT && sudo systemctl restart lernmanager"
    echo ""
}

# Run main function
main "$@"
