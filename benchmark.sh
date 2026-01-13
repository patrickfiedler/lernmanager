#!/bin/bash
# benchmark.sh - Quick performance benchmark using curl
# Run on your VPS to test basic performance

echo "==================================="
echo "Lernmanager Performance Benchmark"
echo "==================================="
echo

# Test 1: Static file
echo "Test 1: Static CSS file"
curl -w "Time: %{time_total}s, Size: %{size_download} bytes\n" \
     -o /dev/null -s \
     http://localhost:8080/static/style.css

# Test 2: Login page
echo "Test 2: Login page"
curl -w "Time: %{time_total}s, Size: %{size_download} bytes\n" \
     -o /dev/null -s \
     http://localhost:8080/

# Test 3: Multiple concurrent requests
echo "Test 3: 10 concurrent requests"
time for i in {1..10}; do
    curl -s http://localhost:8080/ > /dev/null &
done
wait

echo
echo "Benchmark complete!"
