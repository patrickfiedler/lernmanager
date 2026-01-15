#!/usr/bin/env python3
"""
Benchmark script to measure the performance impact of activity logging.

Tests:
1. Direct database write time (INSERT + COMMIT)
2. Full log_analytics_event() function
3. Comparison with/without logging
"""

import time
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import models


def test_database_connection():
    """Test that database connection works (including encryption if enabled)."""
    try:
        with models.db_session() as conn:
            # Try to read from a table to verify encryption key is correct
            result = conn.execute('SELECT COUNT(*) FROM analytics_events').fetchone()
            count = result[0]
        return True, f"Database connection OK (found {count} analytics events)"
    except Exception as e:
        return False, f"Database connection FAILED: {e}"


def benchmark_db_write(iterations=100):
    """Measure raw database INSERT + COMMIT time."""
    times = []

    for i in range(iterations):
        start = time.perf_counter()

        with models.db_session() as conn:
            conn.execute('''
                INSERT INTO analytics_events (event_type, user_id, user_type, metadata)
                VALUES (?, ?, ?, ?)
            ''', ('benchmark_test', 1, 'admin', json.dumps({'iteration': i})))

        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        times.append(elapsed)

    return times


def benchmark_log_function(iterations=100):
    """Measure log_analytics_event() function time."""
    times = []

    for i in range(iterations):
        start = time.perf_counter()

        models.log_analytics_event(
            event_type='benchmark_test',
            user_id=1,
            user_type='admin',
            metadata={'iteration': i, 'route': 'test', 'method': 'GET', 'path': '/test'}
        )

        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        times.append(elapsed)

    return times


def print_stats(times, label):
    """Print statistics for timing results."""
    avg = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)
    median = sorted(times)[len(times) // 2]

    print(f"\n{label}:")
    print(f"  Average: {avg:.2f} ms")
    print(f"  Median:  {median:.2f} ms")
    print(f"  Min:     {min_time:.2f} ms")
    print(f"  Max:     {max_time:.2f} ms")
    print(f"  Total:   {sum(times):.2f} ms for {len(times)} iterations")


def cleanup_benchmark_data():
    """Remove benchmark test entries from database."""
    with models.db_session() as conn:
        result = conn.execute(
            "DELETE FROM analytics_events WHERE event_type = 'benchmark_test'"
        )
        deleted = result.rowcount
    print(f"\nCleaned up {deleted} benchmark entries from database")


def check_sqlite_settings():
    """Check SQLite configuration settings that affect performance."""
    with models.db_session() as conn:
        settings = {
            'synchronous': conn.execute('PRAGMA synchronous').fetchone()[0],
            'journal_mode': conn.execute('PRAGMA journal_mode').fetchone()[0],
            'wal_autocheckpoint': conn.execute('PRAGMA wal_autocheckpoint').fetchone()[0],
        }

    print("\nSQLite Configuration:")
    print(f"  synchronous:        {settings['synchronous']} (0=OFF, 1=NORMAL, 2=FULL, 3=EXTRA)")
    print(f"  journal_mode:       {settings['journal_mode']}")
    print(f"  wal_autocheckpoint: {settings['wal_autocheckpoint']}")

    return settings


if __name__ == '__main__':
    print("=" * 60)
    print("Activity Logging Performance Benchmark")
    print("=" * 60)

    # Check encryption status
    print("\nDatabase Encryption:")
    if models.USE_SQLCIPHER:
        print(f"  Status: ENABLED (using sqlcipher3)")
        print(f"  Key set: {'Yes' if models.SQLCIPHER_KEY else 'No'}")
    else:
        print(f"  Status: DISABLED (using standard sqlite3)")
        if models.SQLCIPHER_KEY:
            print(f"  Warning: SQLCIPHER_KEY is set but sqlcipher3 not installed")

    # Test database connection first
    print("\nTesting database connection...")
    success, message = test_database_connection()
    print(f"  {message}")

    if not success:
        print("\n❌ Cannot proceed with benchmark - database connection failed")
        print("\nPossible causes:")
        print("  - Incorrect SQLCIPHER_KEY environment variable")
        print("  - Database file not found")
        print("  - Database corruption")
        print("\nPlease verify your configuration and try again.")
        sys.exit(1)

    # Check SQLite settings
    settings = check_sqlite_settings()

    # Run benchmarks
    iterations = 100
    print(f"\nRunning {iterations} iterations...")

    try:
        print("\n1. Benchmarking raw database INSERT + COMMIT...")
        db_times = benchmark_db_write(iterations)
        print_stats(db_times, "Raw Database Write")

        print("\n2. Benchmarking log_analytics_event() function...")
        log_times = benchmark_log_function(iterations)
        print_stats(log_times, "log_analytics_event() Function")
    except Exception as e:
        print(f"\n❌ Benchmark failed: {e}")
        print("\nThis may be due to database encryption or permissions.")
        sys.exit(1)

    # Calculate overhead
    overhead = sum(log_times) - sum(db_times)
    print(f"\nFunction overhead: {overhead:.2f} ms total ({overhead/iterations:.2f} ms per call)")

    # Estimate impact
    print("\n" + "=" * 60)
    print("Performance Impact Estimate:")
    print("=" * 60)
    avg_log_time = sum(log_times) / len(log_times)
    print(f"Each page view adds approximately {avg_log_time:.2f} ms latency")
    print(f"At 100 requests/minute: {avg_log_time * 100 / 1000:.2f} seconds spent logging per minute")

    # Cleanup
    cleanup_benchmark_data()

    print("\n" + "=" * 60)
    print("Recommendations:")
    print("=" * 60)

    if avg_log_time > 20:
        print("⚠️  HIGH IMPACT: Logging adds significant latency")
        print("   Consider async logging or batching")
    elif avg_log_time > 10:
        print("⚠️  MODERATE IMPACT: Logging adds noticeable latency")
        print("   Consider optimizations if user experience is affected")
    else:
        print("✓  LOW IMPACT: Logging overhead is minimal")

    if settings['synchronous'] == 2:
        print("\n💡 OPTIMIZATION: synchronous=FULL mode is very safe but slow")
        print("   Consider WAL mode + synchronous=NORMAL for better performance")

    if settings['journal_mode'] != 'wal':
        print("\n💡 OPTIMIZATION: Not using WAL (Write-Ahead Logging)")
        print("   WAL mode can improve write performance significantly")

    # Note about encryption
    if models.USE_SQLCIPHER:
        print("\n📝 NOTE: Database encryption is enabled")
        print("   Encryption adds ~1-2ms overhead but is important for security")
        print("   Performance measurements include encryption overhead")
