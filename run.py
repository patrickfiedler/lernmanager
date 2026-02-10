#!/usr/bin/env python3
"""
Lernmanager - Production Server
Run with: python run.py
"""

from waitress import serve
from app import app, init_app

if __name__ == '__main__':
    # Initialize database and create directories
    init_app()

    print("=" * 50)
    print("📚 Lernmanager")
    print("=" * 50)
    print("Server läuft auf: http://localhost:8080")
    print("Admin-Login: admin / admin")
    print("=" * 50)
    print("Zum Beenden: Strg+C")
    print()

    # Run with waitress - configured for file uploads
    serve(
        app,
        host='0.0.0.0',
        port=8080,
        threads=16,                   # Worker threads (handles concurrent class access)
        channel_timeout=120,          # Timeout for connections (2 minutes)
        recv_bytes=65536,             # 64KB receive buffer (for uploads)
        send_bytes=262144,            # 256KB send buffer (faster large file responses)
        max_request_body_size=67108864  # 64MB (matches Flask's MAX_CONTENT_LENGTH)
    )
