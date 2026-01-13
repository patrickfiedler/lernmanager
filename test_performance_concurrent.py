#!/usr/bin/env python3
"""
test_performance_concurrent.py
Tests how the server handles concurrent requests

Usage:
    python3 test_performance_concurrent.py
"""

import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

def make_request(url, request_num):
    """Single request with timing"""
    try:
        start = time.time()
        response = requests.get(url, timeout=30)
        elapsed = time.time() - start
        return {
            'num': request_num,
            'status': response.status_code,
            'time': elapsed,
            'success': response.status_code == 200
        }
    except Exception as e:
        return {
            'num': request_num,
            'status': 0,
            'time': 0,
            'success': False,
            'error': str(e)
        }

def test_concurrent(url, num_requests=20, num_workers=5):
    """Test with multiple concurrent requests"""
    print(f"Testing {url}")
    print(f"  Total requests: {num_requests}")
    print(f"  Concurrent workers: {num_workers}")
    print()

    start_time = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(make_request, url, i)
            for i in range(num_requests)
        ]

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status = "✓" if result['success'] else "✗"
            print(f"  Request {result['num']:2d}: {status} {result['time']*1000:6.1f}ms")

    total_time = time.time() - start_time

    # Calculate statistics
    successful = [r for r in results if r['success']]
    failed = len(results) - len(successful)

    if successful:
        times = [r['time'] for r in successful]
        avg_time = sum(times) / len(times)
        throughput = len(successful) / total_time

        print()
        print(f"Results:")
        print(f"  Total time:     {total_time:.2f}s")
        print(f"  Successful:     {len(successful)}/{num_requests}")
        print(f"  Failed:         {failed}")
        print(f"  Avg response:   {avg_time*1000:.1f}ms")
        print(f"  Throughput:     {throughput:.2f} req/s")
    else:
        print("\nAll requests failed!")

def main():
    base_url = "http://localhost:8080"

    print("=" * 60)
    print("CONCURRENT LOAD TEST")
    print("=" * 60)
    print()

    # Test 1: Light load (simulates 5 students browsing)
    print("\nTest 1: Light load (5 concurrent users)")
    print("-" * 60)
    test_concurrent(base_url + "/", num_requests=20, num_workers=5)

    # Test 2: Medium load (simulates class of 15 students)
    print("\n\nTest 2: Medium load (15 concurrent users)")
    print("-" * 60)
    test_concurrent(base_url + "/", num_requests=30, num_workers=15)

    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
