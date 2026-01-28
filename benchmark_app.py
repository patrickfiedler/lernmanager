#!/usr/bin/env python3
"""
Benchmark script to measure page generation performance.

This script simulates requests to different routes and measures:
- Database query time
- Template rendering time
- Total response time

Run this on both your laptop and server to compare hardware performance.

Usage:
    python benchmark_app.py
    python benchmark_app.py --iterations 100
    python benchmark_app.py --verbose
"""

import sys
import time
import argparse
from contextlib import contextmanager
import statistics

# Import app components
import models
from app import app


@contextmanager
def timer(label):
    """Context manager to time code blocks."""
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    print(f"  {label}: {elapsed*1000:.2f}ms")
    return elapsed


def benchmark_database_queries(iterations=10):
    """Benchmark common database queries."""
    print("\n=== Database Query Benchmarks ===")

    times = []

    # Get all classes
    print(f"\n1. get_all_klassen() - {iterations} iterations:")
    for i in range(iterations):
        start = time.perf_counter()
        models.get_all_klassen()
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)

    print(f"  Min:    {min(times):.2f}ms")
    print(f"  Max:    {max(times):.2f}ms")
    print(f"  Mean:   {statistics.mean(times):.2f}ms")
    print(f"  Median: {statistics.median(times):.2f}ms")

    # Get all tasks
    print(f"\n2. get_all_tasks() - {iterations} iterations:")
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        models.get_all_tasks()
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)

    print(f"  Min:    {min(times):.2f}ms")
    print(f"  Max:    {max(times):.2f}ms")
    print(f"  Mean:   {statistics.mean(times):.2f}ms")
    print(f"  Median: {statistics.median(times):.2f}ms")

    # Get students in first class (if exists)
    klassen = models.get_all_klassen()
    if klassen:
        klasse_id = klassen[0]['id']
        print(f"\n3. get_students_in_klasse({klasse_id}) - {iterations} iterations:")
        times = []
        for i in range(iterations):
            start = time.perf_counter()
            models.get_students_in_klasse(klasse_id)
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)

        print(f"  Min:    {min(times):.2f}ms")
        print(f"  Max:    {max(times):.2f}ms")
        print(f"  Mean:   {statistics.mean(times):.2f}ms")
        print(f"  Median: {statistics.median(times):.2f}ms")


def benchmark_template_rendering(iterations=10):
    """Benchmark template rendering with test client."""
    print("\n\n=== Template Rendering Benchmarks ===")

    with app.test_client() as client:
        # Login page (no auth required)
        print(f"\n1. Login page - {iterations} iterations:")
        times = []
        for i in range(iterations):
            start = time.perf_counter()
            response = client.get('/login')
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)
            assert response.status_code == 200

        print(f"  Min:    {min(times):.2f}ms")
        print(f"  Max:    {max(times):.2f}ms")
        print(f"  Mean:   {statistics.mean(times):.2f}ms")
        print(f"  Median: {statistics.median(times):.2f}ms")

        # Get first admin and student directly from database
        klassen = models.get_all_klassen()

        # Try to get an admin ID
        print(f"\n2. Testing authenticated admin pages:")
        with client.session_transaction() as sess:
            sess['admin_id'] = 1  # Assume admin ID 1 exists

        # Admin dashboard (authenticated)
        print(f"\n  Admin dashboard - {iterations} iterations:")
        times = []
        for i in range(iterations):
            start = time.perf_counter()
            response = client.get('/admin')
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)
            # Will redirect if no admin with ID 1
            if response.status_code not in [200, 302]:
                print(f"    Warning: Unexpected status {response.status_code}")
                break

        if times:
            print(f"    Min:    {min(times):.2f}ms")
            print(f"    Max:    {max(times):.2f}ms")
            print(f"    Mean:   {statistics.mean(times):.2f}ms")
            print(f"    Median: {statistics.median(times):.2f}ms")

        # Class list page
        if klassen and len(klassen) > 0:
            klasse_id = klassen[0]['id']
            print(f"\n  Class detail page (ID {klasse_id}) - {iterations} iterations:")
            times = []
            for i in range(iterations):
                start = time.perf_counter()
                response = client.get(f'/admin/klasse/{klasse_id}')
                elapsed = time.perf_counter() - start
                times.append(elapsed * 1000)
                if response.status_code not in [200, 302]:
                    print(f"    Warning: Unexpected status {response.status_code}")
                    break

            if times:
                print(f"    Min:    {min(times):.2f}ms")
                print(f"    Max:    {max(times):.2f}ms")
                print(f"    Mean:   {statistics.mean(times):.2f}ms")
                print(f"    Median: {statistics.median(times):.2f}ms")

        # Student view benchmarks
        print(f"\n3. Testing student pages:")
        with client.session_transaction() as sess:
            sess.clear()
            sess['student_id'] = 1  # Assume student ID 1 exists

        print(f"\n  Student dashboard - {iterations} iterations:")
        times = []
        for i in range(iterations):
            start = time.perf_counter()
            response = client.get('/schueler')
            elapsed = time.perf_counter() - start
            times.append(elapsed * 1000)
            if response.status_code not in [200, 302]:
                print(f"    Warning: Unexpected status {response.status_code}")
                break

        if times:
            print(f"    Min:    {min(times):.2f}ms")
            print(f"    Max:    {max(times):.2f}ms")
            print(f"    Mean:   {statistics.mean(times):.2f}ms")
            print(f"    Median: {statistics.median(times):.2f}ms")

        # Student class view
        if klassen and len(klassen) > 0:
            klasse_id = klassen[0]['id']
            print(f"\n  Student class/task page (ID {klasse_id}) - {iterations} iterations:")
            times = []
            for i in range(iterations):
                start = time.perf_counter()
                response = client.get(f'/schueler/klasse/{klasse_id}')
                elapsed = time.perf_counter() - start
                times.append(elapsed * 1000)
                # May be 200 or 302 depending on task assignment
                if response.status_code not in [200, 302]:
                    print(f"    Warning: Unexpected status {response.status_code}")
                    break

            if times:
                print(f"    Min:    {min(times):.2f}ms")
                print(f"    Max:    {max(times):.2f}ms")
                print(f"    Mean:   {statistics.mean(times):.2f}ms")
                print(f"    Median: {statistics.median(times):.2f}ms")


def benchmark_markdown_rendering(iterations=10):
    """Benchmark markdown to HTML conversion."""
    print("\n\n=== Markdown Rendering Benchmark ===")

    import markdown

    # Sample markdown text (similar to task descriptions)
    sample_markdown = """
# Überschrift 1

Dies ist ein **fetter Text** und dies ist *kursiver Text*.

## Überschrift 2

- Listenelement 1
- Listenelement 2
- Listenelement 3

1. Nummerierte Liste
2. Zweiter Punkt
3. Dritter Punkt

```python
def hello():
    print("Hello World")
```

Das ist ein [Link](https://example.com) und hier ist `inline code`.

> Blockquote mit wichtigen Informationen
> die über mehrere Zeilen geht.

---

**Wichtig:** Dies ist eine wichtige Information!

![Bild](https://example.com/image.png)
"""

    print(f"\nMarkdown to HTML conversion - {iterations} iterations:")
    times = []
    for i in range(iterations):
        start = time.perf_counter()
        html = markdown.markdown(sample_markdown, extensions=['fenced_code', 'tables'])
        elapsed = time.perf_counter() - start
        times.append(elapsed * 1000)

    print(f"  Min:    {min(times):.2f}ms")
    print(f"  Max:    {max(times):.2f}ms")
    print(f"  Mean:   {statistics.mean(times):.2f}ms")
    print(f"  Median: {statistics.median(times):.2f}ms")


def get_system_info():
    """Get system information for comparison."""
    import platform
    import os

    print("\n=== System Information ===")
    print(f"Platform:       {platform.system()} {platform.release()}")
    print(f"Python:         {platform.python_version()}")
    print(f"Processor:      {platform.processor() or 'Unknown'}")
    print(f"CPU cores:      {os.cpu_count()}")

    # Try to get database info
    import config
    db_path = config.DATABASE
    if os.path.exists(db_path):
        db_size = os.path.getsize(db_path) / 1024 / 1024  # MB
        print(f"Database:       {db_path}")
        print(f"Database size:  {db_size:.2f} MB")
        print(f"Encryption:     {'Yes (SQLCipher)' if models.USE_SQLCIPHER else 'No (SQLite)'}")
    else:
        print(f"Database:       {db_path} (not found)")


def main():
    parser = argparse.ArgumentParser(description='Benchmark Lernmanager performance')
    parser.add_argument('-i', '--iterations', type=int, default=10,
                        help='Number of iterations per benchmark (default: 10)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show verbose output')
    parser.add_argument('--db-only', action='store_true',
                        help='Only run database benchmarks')
    parser.add_argument('--render-only', action='store_true',
                        help='Only run rendering benchmarks')

    args = parser.parse_args()

    print("=" * 60)
    print("Lernmanager Performance Benchmark")
    print("=" * 60)

    get_system_info()

    if not args.render_only:
        benchmark_database_queries(args.iterations)

    if not args.db_only:
        benchmark_template_rendering(args.iterations)
        benchmark_markdown_rendering(args.iterations)

    print("\n" + "=" * 60)
    print("Benchmark Complete!")
    print("=" * 60)
    print("\nTo compare with server, copy this script to server and run:")
    print("  ssh user@server 'cd /opt/lernmanager && ./venv/bin/python benchmark_app.py'")
    print()


if __name__ == '__main__':
    main()
