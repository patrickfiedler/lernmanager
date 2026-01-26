# Migrate Production Server - Quick Start

## One-Liner Migration (Recommended)

Run this from your local machine to migrate your production server:

```bash
ssh user@your-server 'sudo bash -s' << 'ENDSSH'
cd /opt/lernmanager

# Extract secrets from current service file
SECRET_KEY=$(grep 'Environment="SECRET_KEY=' /etc/systemd/system/lernmanager.service | sed -n 's/.*SECRET_KEY=\([^"]*\).*/\1/p')
SQLCIPHER_KEY=$(grep 'Environment="SQLCIPHER_KEY=' /etc/systemd/system/lernmanager.service 2>/dev/null | sed -n 's/.*SQLCIPHER_KEY=\([^"]*\).*/\1/p')
FORCE_HTTPS=$(grep 'Environment="FORCE_HTTPS=' /etc/systemd/system/lernmanager.service 2>/dev/null | sed -n 's/.*FORCE_HTTPS=\([^"]*\).*/\1/p')

# Create .env file with all secrets
cat > /opt/lernmanager/.env << EOF
# Lernmanager Environment Configuration
# Migrated on: $(date)

# Flask secret key (required)
SECRET_KEY=$SECRET_KEY

# Production mode
FLASK_ENV=production
EOF

# Add FORCE_HTTPS if it was set
if [ -n "$FORCE_HTTPS" ]; then
    echo "FORCE_HTTPS=$FORCE_HTTPS" >> /opt/lernmanager/.env
else
    echo "# FORCE_HTTPS=true  # Uncomment after setting up SSL/TLS" >> /opt/lernmanager/.env
fi

# Add SQLCIPHER_KEY if it was set
if [ -n "$SQLCIPHER_KEY" ]; then
    echo "SQLCIPHER_KEY=$SQLCIPHER_KEY" >> /opt/lernmanager/.env
else
    echo "# SQLCIPHER_KEY=CHANGE_ME  # Uncomment to enable database encryption" >> /opt/lernmanager/.env
fi

# Set proper permissions
chmod 600 /opt/lernmanager/.env
chown root:root /opt/lernmanager/.env

echo "✓ Created /opt/lernmanager/.env with extracted secrets"
cat /opt/lernmanager/.env

# Deploy new code (includes automatic migrations!)
/opt/lernmanager/deploy/update.sh
ENDSSH
```

## What This Does

1. ✅ Extracts `SECRET_KEY` from your current service file
2. ✅ Extracts `SQLCIPHER_KEY` if you have database encryption enabled
3. ✅ Extracts `FORCE_HTTPS` if you have HTTPS configured
4. ✅ Creates `/opt/lernmanager/.env` with all secrets
5. ✅ Deploys the new code from GitHub
6. ✅ **Runs `migrate_add_why_learn_this.py` automatically** (fixes your production issue!)
7. ✅ Restarts the service

**Note**: If `SQLCIPHER_KEY` or `FORCE_HTTPS` aren't currently set, they're added as commented placeholders for future use.

## After Migration

Verify everything works:

```bash
# Check service status
ssh user@server 'sudo systemctl status lernmanager'

# Check .env file was created
ssh user@server 'sudo ls -la /opt/lernmanager/.env'

# View logs (should show no errors)
ssh user@server 'sudo journalctl -u lernmanager -n 50 --no-pager'
```

Then test your application in a browser.

## Need More Help?

- **Detailed guide**: See `MIGRATION_GUIDE.md`
- **Troubleshooting**: See `MIGRATION_GUIDE.md` > Troubleshooting section
- **Overview**: See `DEPLOYMENT_IMPROVEMENTS_SUMMARY.md`
