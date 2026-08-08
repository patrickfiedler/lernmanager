#!/bin/bash
#
# Manually unlock + mount the LUKS-encrypted /opt/lernmanager data volume
# and start the app. Needed after every server reboot - see
# docs/2026-08-08_luks_container_setup.md for why this isn't automated.
#
# Idempotent: safe to re-run if a previous attempt (e.g. a pending
# crypttab boot-time password prompt) left things half set up.
#
# Usage: sudo ./unlock_data_volume.sh
#
set -e

IMG=/root/luks-container.img
MAPPER=luks-container
MOUNT=/opt/lernmanager

# 1. Attach the loop device, if not already attached
LOOPDEV=$(losetup -j "$IMG" | cut -d: -f1)
if [ -z "$LOOPDEV" ]; then
    echo "Attaching loop device..."
    LOOPDEV=$(losetup --show -f "$IMG")
fi
echo "Loop device: $LOOPDEV"

# 2. Unlock the LUKS container, if not already open (prompts for passphrase)
if [ ! -e "/dev/mapper/$MAPPER" ]; then
    echo "Unlocking..."
    cryptsetup open "$LOOPDEV" "$MAPPER"
else
    echo "Already unlocked."
fi

# 3. Mount, if not already mounted
if ! mountpoint -q "$MOUNT"; then
    echo "Mounting..."
    mount "/dev/mapper/$MAPPER" "$MOUNT"
else
    echo "Already mounted."
fi

# 4. Start the app
systemctl start lernmanager
sleep 2
systemctl status lernmanager --no-pager

# 5. Verify it's actually responding
curl -s -o /dev/null -w "HTTP %{http_code}\n" http://127.0.0.1:8080
