#!/usr/bin/env python3
"""
Lernfortschritt - Production Server
Run with: python run.py
"""

from waitress import serve
from app import app, init_app

if __name__ == '__main__':
    # Initialize database and create directories
    init_app()

    print("=" * 50)
    print("📚 Lernfortschritt")
    print("=" * 50)
    print("Server läuft auf: http://localhost:8080")
    print("Admin-Login: admin / admin")
    print("=" * 50)
    print("Zum Beenden: Strg+C")
    print()

    # Run with waitress
    serve(app, host='0.0.0.0', port=8080)
