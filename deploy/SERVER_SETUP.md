# Server Setup Guide for Lernmanager

This guide walks you through setting up Lernmanager on a fresh Linux VServer.

## Prerequisites

- Ubuntu/Debian-based VServer
- SSH access with sudo privileges
- Domain name pointing to your server's IP
- Git repository URL (your repo must be accessible from the server)

## 1. Install System Dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git nginx certbot python3-certbot-nginx ufw
```

## 2. Create Application User

```bash
# Create system user without login shell
sudo useradd -r -s /usr/sbin/nologin -m -d /opt/lernmanager lernmanager
```

## 3. Clone Repository

```bash
# Clone as root, then change ownership
sudo git clone YOUR_REPO_URL /opt/lernmanager
sudo chown -R lernmanager:lernmanager /opt/lernmanager
```

**Note:** If your repo is private, you'll need to set up deploy keys or use HTTPS with credentials.

## 4. Set Up Python Environment

```bash
# Create virtual environment
sudo -u lernmanager python3 -m venv /opt/lernmanager/venv

# Install dependencies
sudo -u lernmanager /opt/lernmanager/venv/bin/pip install -r /opt/lernmanager/requirements.txt
```

## 5. Create Data Directories

```bash
sudo -u lernmanager mkdir -p /opt/lernmanager/data
sudo -u lernmanager mkdir -p /opt/lernmanager/static/uploads
```

## 6. Configure Systemd Service

```bash
# Copy service file
sudo cp /opt/lernmanager/deploy/lernmanager.service /etc/systemd/system/

# Generate a secure secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
echo "Your SECRET_KEY: $SECRET_KEY"

# Edit the service file to add your secret key
sudo nano /etc/systemd/system/lernmanager.service
# Replace CHANGE_ME_TO_RANDOM_STRING with the generated key

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable lernmanager
sudo systemctl start lernmanager

# Check status
sudo systemctl status lernmanager
```

## 7. Configure Nginx

```bash
# Copy nginx config
sudo cp /opt/lernmanager/deploy/nginx.conf /etc/nginx/sites-available/lernmanager

# Edit to set your domain
sudo nano /etc/nginx/sites-available/lernmanager
# Replace DOMAIN.TLD with your actual domain

# Enable site
sudo ln -s /etc/nginx/sites-available/lernmanager /etc/nginx/sites-enabled/

# Remove default site (optional)
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

## 8. Set Up HTTPS with Let's Encrypt

```bash
sudo certbot --nginx -d YOUR_DOMAIN.TLD
```

Follow the prompts. Certbot will automatically configure nginx for HTTPS and set up auto-renewal.

## 9. Configure Firewall

```bash
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

## 10. Set Up Passwordless Sudo for Deployments (Optional)

To allow deployment without entering a password:

```bash
# Create sudoers file for deploy user
sudo visudo -f /etc/sudoers.d/lernmanager-deploy
```

Add this line (replace `deployuser` with your SSH user):
```
deployuser ALL=(ALL) NOPASSWD: /bin/systemctl restart lernmanager, /bin/systemctl status lernmanager
```

## Deployment Workflow

After initial setup, deploy updates with:

```bash
# From your local machine
LERNMANAGER_SERVER=user@your-server.de ./deploy/deploy.sh
```

Or set the environment variable permanently:
```bash
export LERNMANAGER_SERVER=user@your-server.de
./deploy/deploy.sh
```

## Troubleshooting

### Check Application Logs
```bash
sudo journalctl -u lernmanager -f
```

### Check Nginx Logs
```bash
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log
```

### Restart Services
```bash
sudo systemctl restart lernmanager
sudo systemctl restart nginx
```

### Test Application Directly
```bash
# Test if waitress is responding
curl http://127.0.0.1:8080
```

## Security Notes

1. **Change default admin password** after first login
2. **Keep SECRET_KEY secret** - never commit it to git
3. **Regular updates**: `sudo apt update && sudo apt upgrade`
4. **Backup database**: `/opt/lernmanager/data/mbi_tracker.db`
