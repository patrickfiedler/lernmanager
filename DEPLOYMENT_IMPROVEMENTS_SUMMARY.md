# Deployment Improvements - Implementation Summary

## What Was Implemented

Two major improvements to your deployment system:

### 1. EnvironmentFile-Based Secrets Management ✅

**Problem Solved**: Secrets were being extracted from and injected into the systemd service file using fragile `sed` parsing. This could fail if the service file format changed.

**Solution**: Secrets now stored in `/opt/lernmanager/.env` and loaded via systemd's `EnvironmentFile=` directive.

**Changes Made**:
- `deploy/lernmanager.service` - Uses `EnvironmentFile=/opt/lernmanager/.env`
- `deploy/setup.sh` - Creates `.env` file with generated secrets
- `deploy/update.sh` - Simplified (no more sed injection, just copies service file)

**Benefits**:
- ✅ Secrets persist across all service file updates
- ✅ No risk of secret loss during deployments
- ✅ Easy to modify secrets (edit `.env`, restart service)
- ✅ Follows systemd best practices
- ✅ Simpler deployment scripts (~40 lines removed)

---

### 2. Automatic Database Migration Execution ✅

**Problem Solved**: Database migrations had to be run manually after deployment, which you forgot to do (causing the production breakage).

**Solution**: `update.sh` now automatically detects and runs migrations.

**How It Works**:
1. Update script checks if any `migrate_*.py` files changed in the commit
2. If yes, runs ALL migration scripts in the repo
3. Migrations are idempotent (safe to run multiple times)
4. Automatically exports `SQLCIPHER_KEY` from `.env` for encrypted databases
5. Reports success/failure and continues deployment with warning if migrations fail

**Changes Made**:
- `deploy/update.sh` - Added Step 6/8: "Checking Database Migrations"
- Detects migration file changes
- Executes all `migrate_*.py` files
- Displays migration status in deployment summary

**Benefits**:
- ✅ Migrations run automatically on deployment
- ✅ No manual intervention needed
- ✅ Prevents issues like the one you just experienced
- ✅ Works with SQLCipher-encrypted databases
- ✅ Safe (migrations check if already applied)

---

## Files Modified

### Core Deployment Files

1. **deploy/lernmanager.service**
   - Removed inline secret environment variables
   - Added `EnvironmentFile=/opt/lernmanager/.env`

2. **deploy/setup.sh**
   - Creates `/opt/lernmanager/.env` with generated `SECRET_KEY`
   - Includes template for `SQLCIPHER_KEY` and `FORCE_HTTPS`
   - No longer injects secrets into service file

3. **deploy/update.sh**
   - Removed secret extraction/injection logic (~30 lines)
   - Added automatic migration detection and execution
   - Updated to 8-step process (was 7 steps)
   - Added migration status to deployment summary

### Documentation

4. **MIGRATION_GUIDE.md** (NEW)
   - Complete guide for migrating existing deployments
   - Automated one-liner migration script
   - Manual migration steps
   - Troubleshooting guide

5. **deployment_improvements_plan.md** (NEW)
   - Implementation plan and tracking
   - Design decisions documented

6. **secrets_management_notes.md** (NEW)
   - Research on all options considered
   - Comparison of 5 different approaches

7. **secrets_management_recommendation.md** (NEW)
   - Detailed recommendation with rationale
   - Before/after comparisons

---

## What You Need to Do

### For Your Production Server (IMPORTANT!)

Your production server is still using the OLD method. You need to migrate it:

**Option A: Automated Migration (Recommended)**

Run this one-liner from your local machine:

```bash
ssh user@your-server 'sudo bash -s' << 'ENDSSH'
cd /opt/lernmanager

# Extract current secrets from service file
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

echo "✓ Created /opt/lernmanager/.env"
cat /opt/lernmanager/.env

# Deploy new code (includes automatic migrations!)
/opt/lernmanager/deploy/update.sh
ENDSSH
```

**What the script does**:
1. Extracts `SECRET_KEY`, `SQLCIPHER_KEY`, and `FORCE_HTTPS` from current service file
2. Creates `/opt/lernmanager/.env` with all extracted secrets
3. Deploys the new code
4. **Runs database migrations automatically** (fixing your current production issue!)
5. Restarts the service

**Note**: If `SQLCIPHER_KEY` or `FORCE_HTTPS` aren't set, they're added as commented placeholders.

**Option B: Follow Manual Steps**

See `MIGRATION_GUIDE.md` for detailed step-by-step instructions.

---

### Testing the Changes

After migration, verify:

1. **Service is running**:
   ```bash
   ssh user@server 'sudo systemctl status lernmanager'
   ```

2. **Environment file exists**:
   ```bash
   ssh user@server 'sudo ls -la /opt/lernmanager/.env'
   # Should show: -rw------- 1 root root
   ```

3. **Application works**:
   - Access your site
   - Log in
   - Navigate around
   - Check logs: `ssh user@server 'sudo journalctl -u lernmanager -n 50'`

---

## Example: How Updates Work Now

### Before (OLD method):

```bash
# update.sh would:
1. Pull new code
2. Check if service file changed
3. If yes:
   - Extract SECRET_KEY with sed: grep | sed -n 's/.*"\(.*\)".*/\1/p'
   - Copy new service file
   - Inject SECRET_KEY back with sed: sed -i "s/CHANGE_ME/$SECRET_KEY/"
   - Hope the sed regex still matches! 🤞
4. Restart service
5. Manually run migrations (if you remember!)
```

### After (NEW method):

```bash
# update.sh now:
1. Pull new code
2. Check if service file changed
3. If yes:
   - Copy new service file (no modification needed!)
4. Check for new migrations
5. If found:
   - Export SQLCIPHER_KEY from .env
   - Run all migrate_*.py files automatically
   - Report results
6. Restart service
7. Everything just works! ✨
```

---

## .env File Format

Your new `/opt/lernmanager/.env` file will look like:

```bash
# Lernmanager Environment Configuration
# Generated on: 2026-01-26

# Flask secret key (required)
SECRET_KEY=abc123def456...64_character_hex_string

# Production mode
FLASK_ENV=production

# HTTPS-only cookies (uncomment after setting up SSL/TLS)
# FORCE_HTTPS=true

# Database encryption (optional)
# SQLCIPHER_KEY=xyz789...
```

**Permissions**: `-rw------- root:root` (600, only root can read/write)

---

## Migration Detection Logic

The update script detects migrations by:

```bash
# Check if any migrate_*.py files changed in this deployment
if git diff --name-only "$CURRENT_COMMIT" "$NEW_COMMIT" | grep -q "^migrate_.*\.py$"; then
    # Count migration files
    MIGRATION_COUNT=$(find "$APP_DIR" -maxdepth 1 -name "migrate_*.py" -type f | wc -l)

    if [ "$MIGRATION_COUNT" -gt 0 ]; then
        # Run all migrations (they're idempotent)
        for migration in "$APP_DIR"/migrate_*.py; do
            sudo -u lernmanager venv/bin/python "$migration"
        done
    fi
fi
```

**Why run ALL migrations?**
- They're idempotent (check if already applied)
- Simple and reliable
- No state tracking needed
- Catches any migrations that were skipped before

---

## Troubleshooting

### If deployment fails after migration

1. **Check .env exists**:
   ```bash
   sudo ls -la /opt/lernmanager/.env
   ```

2. **Check .env has SECRET_KEY**:
   ```bash
   sudo cat /opt/lernmanager/.env | grep SECRET_KEY
   ```

3. **Check service logs**:
   ```bash
   sudo journalctl -u lernmanager -n 100 --no-pager
   ```

4. **Verify service sees environment**:
   ```bash
   sudo systemctl show lernmanager | grep Environment
   ```

See `MIGRATION_GUIDE.md` for detailed troubleshooting.

---

## Future Deployments

### Normal Code Updates

Just commit, push, and run:
```bash
ssh user@server 'sudo /opt/lernmanager/deploy/update.sh'
```

The script will:
- Pull latest code
- Update dependencies if needed
- Update service file if changed (secrets safe in .env)
- **Run migrations automatically** if new ones detected
- Restart service
- Show summary

### Adding New Migrations

1. Create `migrate_something_new.py` in repo root
2. Make it idempotent (check if already applied)
3. Commit and push
4. Run `update.sh`
5. Migration runs automatically! 🎉

### Modifying Secrets

```bash
# Edit .env
ssh user@server 'sudo nano /opt/lernmanager/.env'

# Restart service
ssh user@server 'sudo systemctl restart lernmanager'
```

No need to touch the service file!

---

## Rollback Strategy

If you need to rollback for any reason:

```bash
# Rollback code
cd /opt/lernmanager
sudo -u lernmanager git reset --hard <previous-commit>
sudo systemctl restart lernmanager
```

The `.env` file persists, so secrets are safe.

---

## Next Steps

1. **Migrate your production server** using Option A or B above
2. **Test the migration** thoroughly
3. **Commit and push** these changes to GitHub
4. **Update your deployment docs** if needed
5. **Future deployments** will be simpler and safer!

---

## Questions?

- All changes documented in `deployment_improvements_plan.md`
- Migration steps in `MIGRATION_GUIDE.md`
- Design rationale in `secrets_management_recommendation.md`

The implementation is complete and ready for production migration!
