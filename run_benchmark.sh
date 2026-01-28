#!/bin/bash
#
# Helper script to run benchmark with SQLCipher support
#
# This script extracts only SQLCIPHER_KEY from .env (if present)
# and runs the benchmark with encryption support enabled.
#
# Usage:
#   ./run_benchmark.sh [benchmark options]
#
# Examples:
#   ./run_benchmark.sh                      # Run with defaults
#   ./run_benchmark.sh --iterations 50      # Run 50 iterations
#   ./run_benchmark.sh --db-only            # Only database benchmarks
#

set -e  # Exit on error

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Extract only SQLCIPHER_KEY from .env if it exists
# (We only extract this specific variable, not all .env contents)
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    # Securely extract only SQLCIPHER_KEY (doesn't expose other secrets)
    SQLCIPHER_KEY=$(grep '^SQLCIPHER_KEY=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [ -n "$SQLCIPHER_KEY" ]; then
        export SQLCIPHER_KEY
        echo "SQLCipher encryption: enabled"
    else
        echo "Note: SQLCIPHER_KEY not found in .env"
    fi
else
    echo "Note: No .env file found at $ENV_FILE"
fi

# Detect Python interpreter
if [ -f "$SCRIPT_DIR/venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python"
else
    PYTHON="python3"
fi

# Run benchmark
echo ""
exec "$PYTHON" "$SCRIPT_DIR/benchmark_app.py" "$@"
