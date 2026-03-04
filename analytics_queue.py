"""
Asynchronous analytics event queue.

This module provides a thread-safe queue for analytics events that are written
to the database in the background. This eliminates blocking on slow disk I/O
during request processing.

Usage:
    from analytics_queue import start_worker, enqueue_event

    # At app startup
    start_worker()

    # To log an event (non-blocking)
    enqueue_event('page_view', user_id=1, user_type='admin', metadata={'path': '/dashboard'})
"""

import queue
import threading
import json
import sys
import time
import atexit
from contextlib import contextmanager
from datetime import datetime

# Thread-safe queue for events
# maxsize=1000 prevents memory issues if disk becomes very slow
event_queue = queue.Queue(maxsize=1000)

# Background worker thread
worker_thread = None
worker_running = False


def enqueue_event(event_type, user_id=None, user_type=None, metadata=None):
    """
    Add an analytics event to the queue (non-blocking).

    Args:
        event_type: Type of event ('login', 'page_view', etc.)
        user_id: ID of user performing action
        user_type: 'admin' or 'student'
        metadata: Dictionary or JSON string of additional data

    Returns:
        True if event was queued, False if queue is full
    """
    try:
        # Convert metadata to JSON string if it's a dict
        if isinstance(metadata, dict):
            metadata_json = json.dumps(metadata)
        else:
            metadata_json = metadata

        event_queue.put_nowait({
            'event_type': event_type,
            'user_id': user_id,
            'user_type': user_type,
            'metadata': metadata_json,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        return True
    except queue.Full:
        # Queue is full - drop event and log warning
        print(f"WARNING: Analytics queue full, dropping event: {event_type}", file=sys.stderr)
        return False


def background_worker():
    """
    Background worker thread that continuously processes queued events.

    This thread runs in a loop, collecting events from the queue and writing
    them to the database in batches for efficiency.
    """
    # Import here to avoid circular imports
    import config
    import sqlite3
    import os

    # Determine if using SQLCipher
    SQLCIPHER_KEY = os.environ.get('SQLCIPHER_KEY')
    USE_SQLCIPHER = False

    if SQLCIPHER_KEY:
        try:
            from sqlcipher3 import dbapi2 as sqlite3
            USE_SQLCIPHER = True
        except ImportError:
            import sqlite3
    else:
        import sqlite3

    # Database connection context manager (local to worker thread)
    @contextmanager
    def db_connection():
        conn = sqlite3.connect(config.DATABASE, timeout=20)
        try:
            if USE_SQLCIPHER and SQLCIPHER_KEY:
                safe_key = SQLCIPHER_KEY.replace('"', '""')
                conn.execute(f'PRAGMA key = "{safe_key}"')

            # Use the same optimizations as main connection
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"ERROR: Analytics worker database error: {e}", file=sys.stderr)
            raise
        finally:
            conn.close()

    print("Analytics worker thread started", file=sys.stderr)

    while worker_running:
        events = []

        try:
            # Wait for first event (with timeout so we can check worker_running)
            try:
                first_event = event_queue.get(timeout=0.5)
                events.append(first_event)
            except queue.Empty:
                continue  # Loop back and check if we should keep running

            # Try to collect up to 9 more events (total 10) without blocking
            for _ in range(9):
                try:
                    events.append(event_queue.get_nowait())
                except queue.Empty:
                    break

            # Write batch to database
            if events:
                try:
                    with db_connection() as conn:
                        conn.executemany('''
                            INSERT INTO analytics_events (event_type, user_id, user_type, metadata, timestamp)
                            VALUES (?, ?, ?, ?, ?)
                        ''', [
                            (e['event_type'], e['user_id'], e['user_type'], e['metadata'], e['timestamp'])
                            for e in events
                        ])

                    # Mark all events as processed
                    for _ in events:
                        event_queue.task_done()

                except Exception as e:
                    print(f"ERROR: Failed to write analytics batch: {e}", file=sys.stderr)
                    # Mark events as done even on failure to prevent queue.join() from hanging
                    for _ in events:
                        event_queue.task_done()

        except Exception as e:
            print(f"ERROR: Analytics worker loop error: {e}", file=sys.stderr)
            time.sleep(1)  # Prevent tight loop on persistent errors

    print("Analytics worker thread stopped", file=sys.stderr)


def start_worker():
    """
    Start the background worker thread.

    This should be called once at application startup.
    """
    global worker_thread, worker_running

    if worker_thread is not None:
        print("WARNING: Analytics worker already started", file=sys.stderr)
        return

    worker_running = True
    worker_thread = threading.Thread(target=background_worker, daemon=True, name="AnalyticsWorker")
    worker_thread.start()

    # Register cleanup on exit
    atexit.register(stop_worker)


def stop_worker(timeout=5):
    """
    Stop the background worker thread and flush remaining events.

    Args:
        timeout: Maximum seconds to wait for queue to flush

    This is automatically called on application shutdown via atexit.
    """
    global worker_running

    if not worker_running:
        return

    print(f"Stopping analytics worker, flushing queue... (max {timeout}s)", file=sys.stderr)
    worker_running = False

    # Wait for queue to empty (or timeout)
    start_time = time.time()
    while not event_queue.empty() and (time.time() - start_time) < timeout:
        time.sleep(0.1)

    remaining = event_queue.qsize()
    if remaining > 0:
        print(f"WARNING: {remaining} analytics events not written (timeout)", file=sys.stderr)
    else:
        print("Analytics queue flushed successfully", file=sys.stderr)


def get_queue_size():
    """
    Get the current number of events in the queue.

    Returns:
        Integer count of queued events

    Useful for monitoring and debugging.
    """
    return event_queue.qsize()
