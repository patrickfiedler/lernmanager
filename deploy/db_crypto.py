#!/usr/bin/env python3
"""
DB Crypto Management for Lernmanager

Handles encrypt, decrypt, rekey, and verify operations with automatic
service management and rollback-on-failure for production safety.

Usage:
    python deploy/db_crypto.py <operation> [options]

Operations:
    verify    Check DB can be decrypted and passes integrity_check
    encrypt   Convert plain SQLite → encrypted (in-place)
    decrypt   Convert encrypted → plain SQLite (new file, original unchanged)
    rekey     Change encryption key in-place

Options:
    --key KEY       Current encryption key (overrides env/file)
    --new-key KEY   New key for rekey (auto-generates if omitted)
    --no-service    Skip service stop/start (dangerous, for offline use only)
    --dry-run       Print what would happen, make no changes

Key resolution order: --key > SQLCIPHER_KEY env var > /opt/lernmanager/.env
"""

import argparse
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from datetime import datetime

# ─── Paths ───────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_DIR, 'data', 'mbi_tracker.db')
ENV_FILE = '/opt/lernmanager/.env'
SERVICE_NAME = 'lernmanager'

# ─── Key Resolution ──────────────────────────────────────────────────────────

def _load_key_from_env_file():
    """Read SQLCIPHER_KEY from /opt/lernmanager/.env if it exists."""
    if not os.path.exists(ENV_FILE):
        return None
    try:
        with open(ENV_FILE) as f:
            for line in f:
                m = re.match(r'^SQLCIPHER_KEY=(["\']?)(.+?)\1\s*$', line.strip())
                if m:
                    return m.group(2)
    except OSError:
        pass
    return None


def resolve_key(cli_arg, env_var='SQLCIPHER_KEY', read_env_file=True):
    """Priority: CLI arg → env var → .env file."""
    if cli_arg:
        return cli_arg
    val = os.environ.get(env_var)
    if val:
        return val
    if read_env_file:
        return _load_key_from_env_file()
    return None


# ─── Service Management ──────────────────────────────────────────────────────

def _systemctl(action, check=True):
    return subprocess.run(
        ['systemctl', action, SERVICE_NAME],
        capture_output=True, text=True, check=check
    )


def service_stop(dry_run=False):
    if dry_run:
        print(f"[dry-run] systemctl stop {SERVICE_NAME}")
        return
    print(f"→ Stopping {SERVICE_NAME} service...")
    result = _systemctl('stop', check=False)
    if result.returncode not in (0, 5):  # 5 = unit not found / already stopped
        print(f"  Warning: systemctl stop returned {result.returncode}: {result.stderr.strip()}")
    # Wait up to 10s for clean shutdown
    for _ in range(10):
        r = _systemctl('is-active', check=False)
        if r.stdout.strip() not in ('active', 'activating'):
            break
        time.sleep(1)
    print(f"✓ Service stopped")


def service_start(dry_run=False):
    if dry_run:
        print(f"[dry-run] systemctl start {SERVICE_NAME}")
        return
    print(f"→ Starting {SERVICE_NAME} service...")
    result = _systemctl('start', check=False)
    if result.returncode != 0:
        print(f"  Warning: systemctl start returned {result.returncode}: {result.stderr.strip()}")
    # Wait up to 10s for active status
    for _ in range(10):
        time.sleep(1)
        r = _systemctl('is-active', check=False)
        if r.stdout.strip() == 'active':
            print(f"✓ Service is active")
            return
    print(f"✗ Service did not become active within 10s")
    subprocess.run(['systemctl', 'status', SERVICE_NAME, '--no-pager'], check=False)
    sys.exit(1)


# ─── DB Helpers ──────────────────────────────────────────────────────────────

def open_encrypted(path, key):
    """Open a SQLCipher database. Raises on wrong key or corrupt DB."""
    from sqlcipher3 import dbapi2 as sqlcipher
    conn = sqlcipher.connect(path)
    safe_key = key.replace('"', '""')
    conn.execute(f'PRAGMA key = "{safe_key}"')
    # This will throw DatabaseError if the key is wrong
    conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    return conn


def wal_checkpoint(path, key=None):
    """Flush WAL into main DB file for a clean read."""
    print("→ Checkpointing WAL...")
    if key:
        conn = open_encrypted(path, key)
    else:
        import sqlite3
        conn = sqlite3.connect(path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print("✓ WAL checkpointed")


def copy_schema_and_data(src_conn, dst_conn):
    """Copy all tables, indexes, and rows from src to dst. Returns (n_tables, n_rows)."""
    cursor = src_conn.cursor()

    cursor.execute("""
        SELECT sql FROM sqlite_master
        WHERE type='table' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
    """)
    for (sql,) in cursor.fetchall():
        dst_conn.execute(sql)

    cursor.execute("""
        SELECT sql FROM sqlite_master
        WHERE type='index' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'
    """)
    for (sql,) in cursor.fetchall():
        dst_conn.execute(sql)

    dst_conn.commit()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    table_names = [r[0] for r in cursor.fetchall()]

    total_rows = 0
    for table in table_names:
        cursor.execute(f"SELECT * FROM {table}")
        rows = cursor.fetchall()
        if rows:
            columns = [d[0] for d in cursor.description]
            placeholders = ', '.join(['?' for _ in columns])
            sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
            for row in rows:
                dst_conn.execute(sql, tuple(row))
            total_rows += len(rows)
            print(f"  Copied {len(rows):5d} rows ← {table}")

    dst_conn.commit()
    return len(table_names), total_rows


def verify_db(path, key=None):
    """Open DB, run integrity_check. Returns (ok: bool, message: str)."""
    try:
        if key:
            conn = open_encrypted(path, key)
        else:
            import sqlite3
            conn = sqlite3.connect(path)
            conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except Exception as e:
        return False, f"Failed to open: {e}"

    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != 'ok':
            conn.close()
            return False, f"integrity_check: {result[0] if result else 'no result'}"

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        total = sum(conn.execute(f"SELECT COUNT(*) FROM {t[0]}").fetchone()[0] for t in tables)
        conn.close()
        return True, f"{len(tables)} tables, {total} rows"
    except Exception as e:
        conn.close()
        return False, f"integrity_check error: {e}"


# ─── Operations ──────────────────────────────────────────────────────────────

def op_verify(key, dry_run=False):
    print(f"\n=== verify ===\n")
    if dry_run:
        print(f"[dry-run] Would open {DB_PATH} with key and run PRAGMA integrity_check")
        return
    ok, msg = verify_db(DB_PATH, key)
    if ok:
        print(f"✓ Integrity check passed ({msg})")
    else:
        print(f"✗ Integrity check failed: {msg}")
        sys.exit(1)


def op_encrypt(key, dry_run=False, no_service=False):
    """Convert plain SQLite → encrypted in-place."""
    print(f"\n=== encrypt ===\n")
    tmp_path = DB_PATH + '.tmp'
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if dry_run:
        print(f"[dry-run] Would:")
        print(f"  1. {'(skip)' if no_service else 'Stop service'}")
        print(f"  2. Checkpoint WAL (plain)")
        print(f"  3. Backup DB → {backup_path}")
        print(f"  4. Encrypt plain DB → {tmp_path}")
        print(f"  5. Verify {tmp_path} with new key")
        print(f"  6. Atomic rename: {tmp_path} → {DB_PATH}")
        print(f"  7. {'(skip)' if no_service else 'Start service'}")
        return

    if not no_service:
        service_stop()

    try:
        wal_checkpoint(DB_PATH, key=None)

        print(f"→ Backing up to {os.path.basename(backup_path)}...")
        shutil.copy2(DB_PATH, backup_path)
        ok, msg = verify_db(backup_path, key=None)
        if not ok:
            raise RuntimeError(f"Backup verification failed: {msg}")
        print(f"✓ Backup verified ({msg})")

        print(f"→ Encrypting...")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        import sqlite3
        from sqlcipher3 import dbapi2 as sqlcipher
        src_conn = sqlite3.connect(DB_PATH)
        dst_conn = sqlcipher.connect(tmp_path)
        safe_key = key.replace('"', '""')
        dst_conn.execute(f'PRAGMA key = "{safe_key}"')
        tables, rows = copy_schema_and_data(src_conn, dst_conn)
        src_conn.close()
        dst_conn.close()
        print(f"✓ Encrypted ({tables} tables, {rows} rows)")

        ok, msg = verify_db(tmp_path, key)
        if not ok:
            raise RuntimeError(f"Verification of encrypted file failed: {msg}")
        print(f"✓ Verified ({msg})")

        os.rename(tmp_path, DB_PATH)
        print(f"✓ Renamed → {DB_PATH}")

    except Exception as e:
        print(f"\n✗ Error during encrypt: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, DB_PATH)
            print(f"✓ Restored from backup")
        if not no_service:
            service_start()
        sys.exit(1)

    if not no_service:
        service_start()

    print(f"\n✓ Encryption complete. Backup: {backup_path}")


def op_decrypt(key, dry_run=False, no_service=False):
    """Convert encrypted → plain SQLite (new file, original unchanged)."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = os.path.join(os.path.dirname(DB_PATH), f"mbi_tracker_plain_{timestamp}.db")
    print(f"\n=== decrypt ===\n")

    if dry_run:
        print(f"[dry-run] Would:")
        print(f"  1. {'(skip)' if no_service else 'Stop service (for WAL consistency)'}")
        print(f"  2. Checkpoint WAL (with key)")
        print(f"  3. Decrypt {DB_PATH} → {out_path}")
        print(f"  4. {'(skip)' if no_service else 'Start service'}")
        print(f"  NOTE: Original encrypted DB is not modified")
        return

    if not no_service:
        service_stop()

    try:
        wal_checkpoint(DB_PATH, key)

        print(f"→ Decrypting to {os.path.basename(out_path)}...")
        from sqlcipher3 import dbapi2 as sqlcipher
        import sqlite3
        src_conn = open_encrypted(DB_PATH, key)
        dst_conn = sqlite3.connect(out_path)
        tables, rows = copy_schema_and_data(src_conn, dst_conn)
        src_conn.close()
        dst_conn.close()
        print(f"✓ Decrypted ({tables} tables, {rows} rows)")

        ok, msg = verify_db(out_path, key=None)
        if not ok:
            raise RuntimeError(f"Verification of plain file failed: {msg}")
        print(f"✓ Verified ({msg})")

    except Exception as e:
        print(f"\n✗ Error during decrypt: {e}")
        if os.path.exists(out_path):
            os.remove(out_path)
        if not no_service:
            service_start()
        sys.exit(1)

    if not no_service:
        service_start()

    print(f"\n✓ Decryption complete: {out_path}")
    print(f"  WARNING: This file is unencrypted. Delete it when done inspecting.")


def op_rekey(key, new_key, dry_run=False, no_service=False):
    """Change encryption key in-place."""
    print(f"\n=== rekey ===\n")
    tmp_path = DB_PATH + '.tmp'
    backup_path = f"{DB_PATH}.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    if dry_run:
        print(f"[dry-run] Would:")
        print(f"  1. {'(skip)' if no_service else 'Stop service'}")
        print(f"  2. Checkpoint WAL (with current key)")
        print(f"  3. Backup DB → {backup_path}")
        print(f"  4. Re-encrypt {DB_PATH} → {tmp_path} with new key")
        print(f"  5. Verify {tmp_path} with new key")
        print(f"  6. Atomic rename: {tmp_path} → {DB_PATH}")
        print(f"  7. Update SQLCIPHER_KEY in {ENV_FILE}")
        print(f"  8. {'(skip)' if no_service else 'Start service'}")
        return

    if not no_service:
        service_stop()

    try:
        wal_checkpoint(DB_PATH, key)

        print(f"→ Backing up to {os.path.basename(backup_path)}...")
        shutil.copy2(DB_PATH, backup_path)
        ok, msg = verify_db(backup_path, key)
        if not ok:
            raise RuntimeError(f"Backup verification failed: {msg}")
        print(f"✓ Backup verified ({msg})")

        print(f"→ Re-encrypting with new key...")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        from sqlcipher3 import dbapi2 as sqlcipher
        src_conn = open_encrypted(DB_PATH, key)
        dst_conn = sqlcipher.connect(tmp_path)
        safe_new_key = new_key.replace('"', '""')
        dst_conn.execute(f'PRAGMA key = "{safe_new_key}"')
        tables, rows = copy_schema_and_data(src_conn, dst_conn)
        src_conn.close()
        dst_conn.close()
        print(f"✓ Re-encrypted ({tables} tables, {rows} rows)")

        ok, msg = verify_db(tmp_path, new_key)
        if not ok:
            raise RuntimeError(f"Verification with new key failed: {msg}")
        print(f"✓ Verified with new key ({msg})")

        os.rename(tmp_path, DB_PATH)
        print(f"✓ Renamed → {DB_PATH}")

    except Exception as e:
        print(f"\n✗ Error during rekey: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if os.path.exists(backup_path):
            shutil.copy2(backup_path, DB_PATH)
            print(f"✓ Restored from backup")
        if not no_service:
            service_start()
        sys.exit(1)

    # Update .env with new key
    if os.path.exists(ENV_FILE):
        print(f"→ Updating {ENV_FILE}...")
        with open(ENV_FILE) as f:
            content = f.read()
        new_content = re.sub(
            r'^SQLCIPHER_KEY=.*$', f'SQLCIPHER_KEY={new_key}',
            content, flags=re.MULTILINE
        )
        with open(ENV_FILE, 'w') as f:
            f.write(new_content)
        print(f"✓ {ENV_FILE} updated")
    else:
        print(f"  NOTE: {ENV_FILE} not found — update SQLCIPHER_KEY manually")

    if not no_service:
        service_start()

    print(f"\n{'='*60}")
    print(f"✓ Rekey complete. Backup: {backup_path}")
    print(f"\n  NEW KEY → {new_key}")
    print(f"{'='*60}")
    print(f"  Record this key securely — it cannot be recovered.")


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='DB Crypto Management for Lernmanager',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  sudo python deploy/db_crypto.py verify
  sudo python deploy/db_crypto.py rekey --dry-run
  sudo python deploy/db_crypto.py decrypt
  sudo python deploy/db_crypto.py rekey --new-key <key>
        """
    )
    parser.add_argument('operation', choices=['verify', 'encrypt', 'decrypt', 'rekey'])
    parser.add_argument('--key', help='Current encryption key (overrides env/file)')
    parser.add_argument('--new-key', dest='new_key', help='New key for rekey (auto-generates if omitted)')
    parser.add_argument('--no-service', action='store_true', help='Skip service stop/start (offline use only)')
    parser.add_argument('--dry-run', action='store_true', help='Print what would happen, make no changes')
    args = parser.parse_args()

    if not args.dry_run:
        try:
            import sqlcipher3  # noqa: F401
        except ImportError:
            print("ERROR: sqlcipher3 not installed.")
            print("Install with: pip install sqlcipher3-binary")
            sys.exit(1)

    if not os.path.exists(DB_PATH) and not args.dry_run:
        print(f"ERROR: Database not found: {DB_PATH}")
        sys.exit(1)

    key = resolve_key(args.key)
    new_key = args.new_key or os.environ.get('SQLCIPHER_NEW_KEY')

    if args.operation == 'verify':
        if not key and not args.dry_run:
            print("ERROR: --key / SQLCIPHER_KEY required for verify")
            sys.exit(1)
        op_verify(key, args.dry_run)

    elif args.operation == 'encrypt':
        if not key and not args.dry_run:
            print("ERROR: --key / SQLCIPHER_KEY required (will become the new encryption key)")
            sys.exit(1)
        op_encrypt(key, args.dry_run, args.no_service)

    elif args.operation == 'decrypt':
        if not key and not args.dry_run:
            print("ERROR: --key / SQLCIPHER_KEY required for decrypt")
            sys.exit(1)
        op_decrypt(key, args.dry_run, args.no_service)

    elif args.operation == 'rekey':
        if not key and not args.dry_run:
            print("ERROR: --key / SQLCIPHER_KEY required (current key)")
            sys.exit(1)
        if not new_key:
            new_key = secrets.token_hex(32)
            print(f"→ Auto-generated new key: {new_key}")
        op_rekey(key, new_key, args.dry_run, args.no_service)


if __name__ == '__main__':
    main()
