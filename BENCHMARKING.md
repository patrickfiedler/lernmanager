# Performance Benchmarking

## Overview

The `benchmark_app.py` script measures page generation performance to help identify whether slowness is due to:
- Server hardware (CPU, disk I/O)
- Network latency
- Code inefficiency

## Running Benchmarks

### On Your Laptop

```bash
python benchmark_app.py
```

### On Your Server

```bash
# Recommended: Use helper script (auto-loads .env)
ssh user@server 'cd /opt/lernmanager && sudo -u lernmanager ./run_benchmark.sh'

# Or with options:
ssh user@server 'cd /opt/lernmanager && sudo -u lernmanager ./run_benchmark.sh --iterations 50'

# Alternative: Run directly with environment loaded
ssh user@server 'cd /opt/lernmanager && sudo -u lernmanager bash -c "set -a; source .env; ./venv/bin/python benchmark_app.py"'
```

**Important:** When running as a different user (e.g., with `sudo -u lernmanager`), the `.env` file is NOT automatically loaded. You must either:
1. Use the `run_benchmark.sh` helper script (recommended - only extracts SQLCIPHER_KEY)
2. Manually pass SQLCIPHER_KEY environment variable

### Options

```bash
# Run more iterations for better accuracy
python benchmark_app.py --iterations 50

# Only test database queries
python benchmark_app.py --db-only

# Only test rendering
python benchmark_app.py --render-only

# Show help
python benchmark_app.py --help
```

### SQLCipher Support

The script automatically detects and uses SQLCipher if:
- `SQLCIPHER_KEY` environment variable is set
- `sqlcipher3-binary` package is installed

The output will show:
- `Encryption: Yes (SQLCipher)` - Using encrypted database
- `Encryption: No (standard SQLite)` - Using unencrypted database
- Warning if SQLCIPHER_KEY is set but package is missing

## What It Measures

### 1. Database Queries
- `get_all_klassen()` - Fetch all classes
- `get_all_tasks()` - Fetch all tasks
- `get_students_in_klasse()` - Fetch students in a class

**Target:** < 1ms average on modern hardware

### 2. Template Rendering
- Login page (unauthenticated)
- Admin dashboard (authenticated)
- Class detail page
- Student dashboard
- Student task page

**Target:** < 10ms average on modern hardware

### 3. Markdown Rendering
- Convert markdown to HTML (typical task description)

**Target:** < 5ms average

## Interpreting Results

### Example: Laptop vs Server Comparison

**Laptop (8-core, NVMe SSD):**
```
Database queries:  0.1-0.2ms
Template rendering: 2-6ms
Markdown rendering: 2ms
```

**Server (2-core VPS, HDD):**
```
Database queries:  5-10ms
Template rendering: 50-100ms
Markdown rendering: 10ms
```

**Analysis:** If server is 10x slower across ALL benchmarks, it's a hardware issue, not code inefficiency.

### When to Worry

- **Database queries > 10ms**: Check disk I/O, consider adding indexes
- **Template rendering > 100ms**: Optimize templates, check for N+1 queries
- **Large variance (min vs max)**: Indicates caching, lazy loading, or system load

### What Caching Can't Fix

If the server is fundamentally slower (older CPU, slower disk), caching helps **repeated requests** but not first requests.

Example:
- First request: Still slow (100ms on slow server vs 5ms on fast laptop)
- Cached request: Fast on both (< 1ms)

But for a learning platform with ~30 students, most requests are first-time (not cached).

## Baseline Results

### Laptop (2026-01-28)
- Platform: Linux 6.18.7-2-cachyos
- CPU: 8 cores
- Database queries: 0.11ms average
- Login page: 1.69ms average
- Admin dashboard: 5.43ms average
- Student dashboard: 7.81ms average

### Server
*TODO: Run benchmark on production server and record results here*

## Next Steps

1. **Run benchmark on laptop:**
   ```bash
   python benchmark_app.py --iterations 50
   ```

2. **Run benchmark on server:**
   ```bash
   ssh user@server 'cd /opt/lernmanager && sudo -u lernmanager ./run_benchmark.sh --iterations 50'
   ```

3. **Compare results:**
   - Look at the "Encryption" line to confirm SQLCipher is being used
   - Compare database query times
   - Compare template rendering times

4. **Interpret:**
   - If server is significantly slower across ALL benchmarks → hardware limitation
   - If server is slower only on specific operations → investigate those operations

## Troubleshooting

**"Encryption: No (standard SQLite)" but database is encrypted:**
- SQLCIPHER_KEY environment variable not set
- Solution: Use `run_benchmark.sh` which extracts SQLCIPHER_KEY from .env
- Manual alternative: `SQLCIPHER_KEY="your-key" python benchmark_app.py`

**Permission denied reading .env:**
- .env file is typically owned by root with restricted permissions
- Run with sudo: `sudo -u lernmanager ./run_benchmark.sh`

**Security note:**
- `run_benchmark.sh` only extracts SQLCIPHER_KEY from .env
- It does NOT export other sensitive variables (SECRET_KEY, etc.)
- Safer than `source .env` which would expose all secrets
