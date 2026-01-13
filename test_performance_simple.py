#!/usr/bin/env python3
"""
test_performance_simple.py
Run on your VPS to test response times

Usage:
    python3 test_performance_simple.py
"""

import time
import requests
from statistics import mean, median, stdev

def test_endpoint(url, num_requests=50):
    """Test endpoint and return timing statistics"""
    times = []
    errors = 0

    print(f"Testing {url} with {num_requests} requests...")

    for i in range(num_requests):
        try:
            start = time.time()
            response = requests.get(url, timeout=10)
            elapsed = time.time() - start

            if response.status_code == 200:
                times.append(elapsed)
            else:
                errors += 1

        except Exception as e:
            errors += 1
            print(f"Request {i+1} failed: {e}")

    if times:
        return {
            'mean': mean(times),
            'median': median(times),
            'min': min(times),
            'max': max(times),
            'stdev': stdev(times) if len(times) > 1 else 0,
            'errors': errors,
            'success_rate': len(times) / num_requests * 100
        }
    else:
        return None

def main():
    # Test configuration
    base_url = "http://localhost:8080"

    endpoints = [
        "/",                       # Login page
        "/static/css/style.css",   # Static CSS file
    ]

    print("=" * 60)
    print("LERNMANAGER PERFORMANCE TEST")
    print("=" * 60)
    print()

    results = {}

    for endpoint in endpoints:
        url = base_url + endpoint
        result = test_endpoint(url, num_requests=50)

        if result:
            results[endpoint] = result
            print(f"\n{endpoint}:")
            print(f"  Mean:    {result['mean']*1000:.1f} ms")
            print(f"  Median:  {result['median']*1000:.1f} ms")
            print(f"  Min:     {result['min']*1000:.1f} ms")
            print(f"  Max:     {result['max']*1000:.1f} ms")
            print(f"  StdDev:  {result['stdev']*1000:.1f} ms")
            print(f"  Success: {result['success_rate']:.1f}%")
        else:
            print(f"\n{endpoint}: FAILED (all requests failed)")

    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
