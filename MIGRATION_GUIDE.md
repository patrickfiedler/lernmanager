# Migration Guide: Secrets Management Update

## Overview

This guide helps you migrate existing Lernmanager deployments to the new EnvironmentFile-based secrets management system.

**What changed**:
- Secrets moved from systemd service file to `/opt/lernmanager/.env`
- Service file now uses `EnvironmentFile=` directive
- Deployment scripts simplified (no more sed injection)
- Database migrations now run automatically during updates

**Benefits**:
- Secrets persist across service file updates
- Simpler, safer deployment process
- Automatic database migration execution

---

## For New Installations

No action needed! Just run the updated setup script:

```bash
curl -sSL https://raw.githubusercontent.com/patrickfiedler/lernmanager/main/deploy/setup.sh | sudo bash
```

The script will automatically create `/opt/lernmanager/.env` with generated secrets.

---

## For Existing Deployments

### Option 1: Automated Migration (Recommended)

Run this one-liner to extract secrets and create `.env` file:

```bash
ssh user@your-server 'sudo bash -s' << 'ENDSSH'
cd /opt/lernmanager

# Extract secrets from current service file
SECRET_KEY=$(grep 'Environment="SECRET_KEY=' /etc/systemd/system/lernmanager.service | sed -n 's/.*SECRET_KEY=\([^"]*\).*/\1/p')
SQLCIPHER_KEY=$(grep 'Environment="SQLCIPHER_KEY=' /etc/systemd/system/lernmanager.service 2>/dev/null | sed -n 's/.*SQLCIPHER_KEY=\([^"]*\).*/\1/p')
FORCE_HTTPS=$(grep 'Environment="FORCE_HTTPS=' /etc/systemd/system/lernmanager.service 2>/dev/null | sed -n 's/.*FORCE_HTTPS=\([^"]*\).*/\1/p')

# Create .env file
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

echo "✓ Created /opt/lernmanager/.env"
cat /opt/lernmanager/.env

# Now deploy the new code
/opt/lernmanager/deploy/update.sh
ENDSSH
```

### Option 2: Manual Migration

**Step 1**: Extract your current secrets

SSH to your server and run:

```bash
sudo grep 'SECRET_KEY=' /etc/systemd/system/lernmanager.service
sudo grep 'SQLCIPHER_KEY=' /etc/systemd/system/lernmanager.service
sudo grep 'FORCE_HTTPS=' /etc/systemd/system/lernmanager.service
```

Copy the values somewhere safe.

**Step 2**: Create `.env` file

```bash
sudo nano /opt/lernmanager/.env
```

Add the following content (replace with your actual values):

```bash
# Lernmanager Environment Configuration

# Flask secret key (required) - paste your SECRET_KEY value here
SECRET_KEY=your_actual_secret_key_from_step_1

# Production mode
FLASK_ENV=production

# HTTPS-only cookies (uncomment if you had FORCE_HTTPS=true)
# FORCE_HTTPS=true

# Database encryption (uncomment if you had SQLCIPHER_KEY set)
# SQLCIPHER_KEY=your_actual_sqlcipher_key
```

**Step 3**: Set proper permissions

```bash
sudo chmod 600 /opt/lernmanager/.env
sudo chown root:root /opt/lernmanager/.env
```

**Step 4**: Deploy the new code

```bash
sudo /opt/lernmanager/deploy/update.sh
```

The update script will:
- Pull the new code
- Deploy the new service file (which uses EnvironmentFile=)
- Run any pending database migrations automatically
- Restart the service

**Step 5**: Verify

```bash
sudo systemctl status lernmanager
```

The service should be running. Test by accessing your application.

---

## Troubleshooting

### Service fails to start after migration

**Check logs**:
```bash
sudo journalctl -u lernmanager -n 100 --no-pager
```

**Common issues**:

1. **`.env` file not found**
   ```
   Error: EnvironmentFile=/opt/lernmanager/.env not found
   ```
   Solution: Create the `.env` file following Option 2 above.

2. **Permission denied reading `.env`**
   ```
   Error: Failed to load environment file
   ```
   Solution: Fix permissions:
   ```bash
   sudo chmod 600 /opt/lernmanager/.env
   sudo chown root:root /opt/lernmanager/.env
   ```

3. **Missing SECRET_KEY**
   ```
   Error: SECRET_KEY is required
   ```
   Solution: Make sure `.env` contains `SECRET_KEY=...` line.

### Verify secrets are loaded correctly

```bash
# Check environment variables the service sees
sudo systemctl show lernmanager | grep Environment
```

You should see `SECRET_KEY` and other variables from your `.env` file.

### Rollback to old version (if needed)

If something goes wrong, you can temporarily rollback:

```bash
cd /opt/lernmanager
sudo -u lernmanager git reset --hard <previous-commit-hash>
sudo systemctl restart lernmanager
```

However, the old service file expects secrets embedded in it. To fully rollback, you'd need to restore the old service file too.

---

## Database Migration Notes

### Automatic Execution

Database migrations now run automatically during deployment when:
- Migration files (`migrate_*.py`) changed in the commit
- Migration files exist in the repository

The update script will:
- Detect changed migration files
- Run ALL migration scripts (they're idempotent)
- Report success/failure for each migration
- Continue deployment even if migrations fail (with warning)

### Manual Migration Execution

If you need to run migrations manually:

```bash
cd /opt/lernmanager

# Run a specific migration
sudo -u lernmanager venv/bin/python migrate_add_why_learn_this.py

# Or run all migrations
for migration in migrate_*.py; do
    sudo -u lernmanager venv/bin/python "$migration"
done
```

### SQLCipher Support

If your database is encrypted, migrations automatically use `SQLCIPHER_KEY` from `.env`:

```bash
# In your .env file:
SQLCIPHER_KEY=your_encryption_key
```

The update script exports this variable when running migrations.

---

## Verifying the Migration

After migration, verify everything works:

1. **Check service status**:
   ```bash
   sudo systemctl status lernmanager
   ```

2. **Check environment file exists**:
   ```bash
   sudo ls -la /opt/lernmanager/.env
   # Should show: -rw------- 1 root root ... .env
   ```

3. **Test the application**:
   - Log in as admin
   - Navigate to different pages
   - Verify no errors

4. **Check logs**:
   ```bash
   sudo journalctl -u lernmanager -n 50 --no-pager
   # Should show no errors
   ```

---

## Post-Migration

### Adding New Secrets

To add new environment variables:

```bash
sudo nano /opt/lernmanager/.env
# Add your variable
sudo systemctl restart lernmanager
```

No need to modify the service file!

### Enabling HTTPS

After setting up SSL/TLS:

```bash
sudo nano /opt/lernmanager/.env
# Uncomment: FORCE_HTTPS=true
sudo systemctl restart lernmanager
```

### Rotating Secrets

To generate a new `SECRET_KEY`:

```bash
# Generate new key
python3 -c "import secrets; print(secrets.token_hex(32))"

# Edit .env and replace SECRET_KEY value
sudo nano /opt/lernmanager/.env

# Restart service
sudo systemctl restart lernmanager
```

**Warning**: Changing `SECRET_KEY` will invalidate all active sessions.

---

## Questions?

If you encounter issues not covered here, check:
- Application logs: `sudo journalctl -u lernmanager -f`
- GitHub issues: https://github.com/patrickfiedler/lernmanager/issues
