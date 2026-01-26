# Deployment Quick Reference

## Common Operations

### Deploy Updates
```bash
# SSH to server and run
sudo /opt/lernmanager/deploy/update.sh

# Or run remotely
ssh user@server 'sudo /opt/lernmanager/deploy/update.sh'
```

What it does automatically:
- Pulls latest code from GitHub
- Updates dependencies if `requirements.txt` changed
- Updates systemd service if changed
- **Runs database migrations if detected**
- Restarts service
- Verifies deployment
- Rolls back on failure

---

## Secrets Management

### View Secrets
```bash
sudo cat /opt/lernmanager/.env
```

### Modify Secrets
```bash
# Edit file
sudo nano /opt/lernmanager/.env

# Restart service to apply
sudo systemctl restart lernmanager
```

### Rotate SECRET_KEY
```bash
# Generate new key
python3 -c "import secrets; print(secrets.token_hex(32))"

# Edit .env and replace SECRET_KEY value
sudo nano /opt/lernmanager/.env

# Restart (invalidates all sessions)
sudo systemctl restart lernmanager
```

### Enable HTTPS Mode
```bash
# After setting up SSL/TLS with certbot
sudo nano /opt/lernmanager/.env
# Uncomment: FORCE_HTTPS=true

sudo systemctl restart lernmanager
```

---

## Database Migrations

### Automatic (Default)
Migrations run automatically during deployment when detected.

### Manual Execution
```bash
cd /opt/lernmanager

# Run specific migration
sudo -u lernmanager venv/bin/python migrate_add_why_learn_this.py

# Run all migrations
for migration in migrate_*.py; do
    sudo -u lernmanager venv/bin/python "$migration"
done
```

### With SQLCipher
```bash
# Export key from .env
export $(sudo grep SQLCIPHER_KEY /opt/lernmanager/.env | xargs)

# Run migration
sudo -E -u lernmanager venv/bin/python migrate_script.py

# Unset for security
unset SQLCIPHER_KEY
```

---

## Service Management

### Check Status
```bash
sudo systemctl status lernmanager
```

### View Logs
```bash
# Follow logs
sudo journalctl -u lernmanager -f

# Last 100 lines
sudo journalctl -u lernmanager -n 100 --no-pager

# Today's logs only
sudo journalctl -u lernmanager --since today
```

### Restart Service
```bash
sudo systemctl restart lernmanager
```

### Reload Service File (after manual edits)
```bash
sudo systemctl daemon-reload
sudo systemctl restart lernmanager
```

---

## Troubleshooting

### Service Won't Start

1. **Check logs**:
   ```bash
   sudo journalctl -u lernmanager -n 50 --no-pager
   ```

2. **Verify .env file**:
   ```bash
   sudo ls -la /opt/lernmanager/.env
   # Should be: -rw------- root root

   sudo cat /opt/lernmanager/.env
   # Should contain SECRET_KEY=...
   ```

3. **Test app directly**:
   ```bash
   cd /opt/lernmanager
   sudo -u lernmanager venv/bin/python app.py
   # Look for error messages
   ```

### Database Issues

1. **Check database exists**:
   ```bash
   sudo ls -la /opt/lernmanager/data/mbi_tracker.db
   ```

2. **Run migrations manually**:
   ```bash
   cd /opt/lernmanager
   for m in migrate_*.py; do sudo -u lernmanager venv/bin/python "$m"; done
   ```

### Deployment Failed

1. **Check what changed**:
   ```bash
   cd /opt/lernmanager
   git log -3 --oneline
   git status
   ```

2. **Manual rollback**:
   ```bash
   cd /opt/lernmanager
   sudo -u lernmanager git reset --hard <previous-commit>
   sudo systemctl restart lernmanager
   ```

3. **Check update.sh logs** (they're verbose):
   - Look for red [ERROR] messages
   - Check which step failed

---

## File Locations

| File | Purpose | Permissions |
|------|---------|-------------|
| `/opt/lernmanager/.env` | Secrets & environment config | `600 root:root` |
| `/opt/lernmanager/data/mbi_tracker.db` | Database | `644 lernmanager:lernmanager` |
| `/opt/lernmanager/instance/uploads/` | Uploaded files | `755 lernmanager:lernmanager` |
| `/etc/systemd/system/lernmanager.service` | Service definition | `644 root:root` |
| `/opt/lernmanager/deploy/update.sh` | Update script | `755 lernmanager:lernmanager` |

---

## Adding New Environment Variables

### In .env file
```bash
sudo nano /opt/lernmanager/.env
# Add new variable: NEW_VAR=value

sudo systemctl restart lernmanager
```

### In service file (non-secrets)
```bash
sudo nano /etc/systemd/system/lernmanager.service
# Add: Environment="NEW_VAR=value"

sudo systemctl daemon-reload
sudo systemctl restart lernmanager
```

Prefer `.env` file for easier management.

---

## Backup

### Before Major Changes
```bash
# Backup database
sudo cp /opt/lernmanager/data/mbi_tracker.db \
       /opt/lernmanager/data/mbi_tracker.db.backup

# Backup .env
sudo cp /opt/lernmanager/.env \
       /opt/lernmanager/.env.backup
```

Migrations create automatic backups with timestamps.

---

## Performance

### Clear Python Cache
```bash
sudo rm -rf /opt/lernmanager/instance/tmp/__pycache__
sudo systemctl restart lernmanager
```

### Monitor Memory
```bash
sudo systemctl status lernmanager
# Check Memory usage
```

### View Active Connections
```bash
sudo ss -tlnp | grep 8080
```

---

## Security

### Check File Permissions
```bash
# .env should be 600 (root only)
sudo ls -la /opt/lernmanager/.env

# App files should be owned by lernmanager
sudo ls -la /opt/lernmanager/

# Database should be readable by lernmanager
sudo ls -la /opt/lernmanager/data/
```

### Update System
```bash
sudo apt update && sudo apt upgrade -y
```

### Firewall (if using ufw)
```bash
sudo ufw status
sudo ufw allow 'Nginx Full'
```

---

## Emergency Procedures

### Service Completely Broken
```bash
# 1. Stop service
sudo systemctl stop lernmanager

# 2. Check what's wrong
sudo journalctl -u lernmanager -n 100 --no-pager

# 3. Fix or rollback
cd /opt/lernmanager
sudo -u lernmanager git reset --hard HEAD~1

# 4. Restart
sudo systemctl start lernmanager
```

### Lost SECRET_KEY
```bash
# Generate new one
NEW_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")

# Update .env
sudo sed -i "s/SECRET_KEY=.*/SECRET_KEY=$NEW_KEY/" /opt/lernmanager/.env

# Restart (all sessions invalidated)
sudo systemctl restart lernmanager
```

**Warning**: This logs out all users.

---

## Getting Help

1. **Check logs first**: `sudo journalctl -u lernmanager -n 100`
2. **Read error messages** - they're usually helpful
3. **Check GitHub issues**: https://github.com/patrickfiedler/lernmanager/issues
4. **Review deployment docs**: `MIGRATION_GUIDE.md`
