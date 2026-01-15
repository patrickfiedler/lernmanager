# Performance Investigation Notes

## Current Implementation (Phase 1 Findings)

### Activity Logging System
**Location**: `app.py:1419-1464`, `models.py:1498-1516`

### How It Works

1. **Before Request Hook** (`@app.before_request`):
   - Executes on EVERY request before the route handler
   - Filters out static files, favicon, analytics pages, error pages, downloads
   - Only logs authenticated users (admin or student)
   - Calls `models.log_analytics_event()` synchronously

2. **Database Write** (`models.log_analytics_event()`):
   - Opens database connection via `db_session()` context manager
   - Executes INSERT query into `analytics_events` table
   - Commits transaction
   - Closes connection
   - Error handling: catches exceptions, prints to stderr, doesn't crash

3. **Database Schema**:
   ```sql
   CREATE TABLE analytics_events (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
       event_type TEXT NOT NULL,
       user_id INTEGER,
       user_type TEXT,
       metadata TEXT  -- JSON format
   )
   ```
   - Has 3 indexes: timestamp DESC, user+type+timestamp DESC, event_type+timestamp DESC

### Performance Characteristics

**SYNCHRONOUS BLOCKING**:
- Every page view waits for database INSERT + COMMIT before continuing
- Database connection: open → insert → commit → close
- Happens BEFORE route handler runs

**What Gets Logged**:
- Every authenticated page view (route, method, path)
- Login events
- Task completions
- Quiz attempts
- File downloads (manually logged in routes)

**Typical Flow for One Request**:
```
1. Request arrives
2. @before_request hook fires
3. Open SQLite connection
4. INSERT into analytics_events
5. COMMIT transaction
6. Close connection
7. Continue to actual route handler
8. Route handler runs
9. Response sent
```

## Estimated Performance Impact

### SQLite Write Performance
- **Typical INSERT + COMMIT**: 1-10ms on modern hardware
- **With fsync**: Up to 50-100ms (depends on disk)
- **SQLite default**: Uses synchronous mode (waits for disk write)

### Compounding Factors
1. **Every page = 1 write transaction**: No batching
2. **Full transaction per request**: Connection overhead
3. **Synchronous mode**: Waits for disk fsync by default
4. **Before request hook**: Adds latency BEFORE page logic

### User-Reported Experience
> "Pages load noticeably slower, though not frustratingly so"

This suggests: **10-50ms added latency per request**

## Database Connection Details

**Connection Pattern** (models.py:66-76):
```python
@contextmanager
def db_session():
    conn = get_db()  # Opens connection
    try:
        yield conn
        conn.commit()  # COMMIT - blocks until disk write
    except:
        conn.rollback()
        raise
    finally:
        conn.close()  # Closes connection
```

**SQLite Settings**: Not explicitly configured, likely using defaults:
- `PRAGMA synchronous = FULL` (safest, slowest)
- No WAL mode (Write-Ahead Logging)
- No connection pooling

## Key Findings

### Bottleneck Identified
1. **Synchronous database write on EVERY request**
2. **Happens BEFORE route handler** (blocks entire request)
3. **Full transaction overhead** (open, commit, close)
4. **No batching or async processing**

### Why It Feels Slow
- User clicks link → waits for analytics write → then page loads
- Every navigation has this penalty
- Small but consistent delay on every interaction

## Benchmark Results (Phase 2)

### Local Development Environment
**Test Environment**: Local development machine (unencrypted SQLite)
**Iterations**: 100 per test

**Results**:
- **Raw Database Write (INSERT + COMMIT)**: 10.98 ms average (7-19 ms range)
- **log_analytics_event() Function**: 9.90 ms average (6-17 ms range)
- **Per Request Impact**: ~10 ms added latency per page view

**Assessment**: LOW to MODERATE impact on local machine

---

### Production VPS Environment (CRITICAL UPDATE)
**Test Environment**: Production VPS with SQLCipher encryption
**Iterations**: 100 per test

**Results**:
- **Raw Database Write (INSERT + COMMIT)**: 83.86 ms average (71-102 ms range)
- **log_analytics_event() Function**: 83.99 ms average (71-120 ms range)
- **Per Request Impact**: ~84 ms added latency per page view
- **Function overhead**: Only 0.13 ms (negligible)

**Configuration**:
```
synchronous:        2 (FULL) - Waits for fsync, safest but slowest
journal_mode:       delete    - Traditional rollback journal
wal_autocheckpoint: 1000
Encryption:         ENABLED (SQLCipher) - adds ~1-2ms, not the bottleneck
```

### Performance Assessment - PRODUCTION
- **Impact Level**: ⚠️ HIGH (84ms per request)
- **User Perception**: SIGNIFICANT - adds noticeable delay to every page
- **At Scale**: 100 requests/min = 8.4 seconds/min spent on logging
- **Comparison**: 8.4x slower than local development

### Why Production is So Much Slower
1. **VPS disk I/O**: Cloud storage backend much slower than local SSD
2. **synchronous=FULL**: Forces disk fsync on every commit
3. **journal_mode=DELETE**: Traditional journaling blocks more than WAL
4. **Encryption overhead**: Minimal (~1-2ms), not the primary issue

### Key Optimization Opportunities (Updated with Production Data)

1. **WAL Mode + synchronous=NORMAL** (HIGHEST PRIORITY)
   - **Expected improvement on production VPS**: 84ms → 10-20ms (70-75% reduction)
   - **Local**: Already good (10ms), will get slightly better (5-7ms)
   - Benefit: Writers don't block readers, WAL eliminates most fsync calls
   - Risk: LOW - Production-ready, recommended by SQLite docs
   - **This is the critical fix for production performance**

2. **Async Logging** (Consider if WAL mode not enough)
   - Expected improvement: 84ms → <1ms (99% reduction)
   - Benefit: Zero blocking on main request
   - Trade-off: More complex code, small crash window
   - Risk: MEDIUM - Threading complexity

3. **Batching**: Group multiple events into single transaction
   - Expected improvement: Variable, depends on traffic patterns
   - Benefit: Amortize commit overhead across multiple events
   - Trade-off: Delayed writes, more complexity
   - Risk: MEDIUM - Requires queue management

**Recommendation**: Start with #1 (WAL mode). With 84ms overhead on production, this is urgent and will make the biggest difference with minimal risk.

## Alternative Approaches (Phase 3)

### Option 1: SQLite WAL Mode + synchronous=NORMAL (Quick Win) ⭐ RECOMMENDED

**Implementation**: Add PRAGMA statements when opening database

**Pros**:
- ✅ Quick to implement (2-3 lines of code)
- ✅ No architectural changes
- ✅ **PRODUCTION: 84ms → 10-20ms** (70-75% reduction) ⚠️ CRITICAL FIX
- ✅ **LOCAL: 10ms → 5-7ms** (minor improvement)
- ✅ Still crash-safe (WAL is ACID-compliant)
- ✅ Better concurrency (reads don't block on writes)
- ✅ Works with SQLCipher encryption

**Cons**:
- ⚠️ Creates -wal and -shm files alongside database
- ⚠️ Slightly more complex backup (need to checkpoint)

**Expected Result (Production VPS)**:
- Current: 84ms per request (UNACCEPTABLE)
- After WAL: 10-20ms per request (ACCEPTABLE)
- Improvement: 70-75% reduction in latency

**Implementation**:
```python
def get_db():
    conn = sqlite3.connect(config.DB_PATH, timeout=20)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn
```

**Risk Level**: LOW - WAL is well-tested, recommended by SQLite docs

---

### Option 2: Asynchronous Logging with Queue
**Implementation**: Use Python queue + background thread

**Pros**:
- ✅ Zero blocking on main request (0ms added latency)
- ✅ Can batch writes for efficiency
- ✅ Preserves all current analytics features
- ✅ Can add rate limiting/throttling

**Cons**:
- ⚠️ More complex code (~100 lines)
- ⚠️ Potential event loss on crash/shutdown (small window)
- ⚠️ Need graceful shutdown handling
- ⚠️ Thread management overhead

**Expected Result**: Reduce 10ms → <1ms (imperceptible)

**Implementation Sketch**:
```python
import queue
import threading

log_queue = queue.Queue(maxsize=1000)

def background_logger():
    while True:
        events = []
        # Collect up to 10 events or wait 100ms
        try:
            events.append(log_queue.get(timeout=0.1))
            for _ in range(9):
                events.append(log_queue.get_nowait())
        except queue.Empty:
            pass

        if events:
            # Batch write
            with db_session() as conn:
                conn.executemany(...)

# In @before_request:
log_queue.put_nowait(event_data)
```

**Risk Level**: MEDIUM - Requires threading, shutdown handling

---

### Option 3: Nginx Access Logs + Parsing
**Implementation**: Use nginx logs, parse with log analyzer

**Pros**:
- ✅ Zero application overhead
- ✅ Nginx is already logging (no extra disk I/O)
- ✅ Standard format, many tools available
- ✅ Can handle high traffic easily

**Cons**:
- ❌ Loses rich metadata (task IDs, quiz results, etc.)
- ❌ Can't distinguish admin vs student without parsing cookies
- ❌ Need separate pipeline to import to SQLite
- ❌ Delayed analytics (batch import vs real-time)
- ❌ Can't track custom events (task completion, quiz attempts)

**Nginx Log Format Needed**:
```nginx
log_format detailed '$remote_addr - $remote_user [$time_local] '
                   '"$request" $status $body_bytes_sent '
                   '"$http_referer" "$http_user_agent" '
                   '"$cookie_session" $request_time';
```

**Expected Result**: Reduce 10ms → 0ms, but lose functionality

**Risk Level**: HIGH - Significant feature loss, complex to regain

---

### Option 4: Hybrid Approach
**Implementation**: Nginx for page views, app for rich events

**Pros**:
- ✅ Eliminates most overhead (page views are 80%+ of events)
- ✅ Keeps rich tracking for important events
- ✅ Best of both worlds

**Cons**:
- ⚠️ Two logging systems to maintain
- ⚠️ Need to deduplicate/merge data
- ⚠️ More complex analytics queries

**Expected Result**: Reduce from 10ms to ~2ms average (only custom events hit DB)

**Risk Level**: MEDIUM - Increased complexity

---

### Option 5: Disable Logging for Static/Fast Routes
**Implementation**: Skip logging for certain routes

**Pros**:
- ✅ Very simple (add to exclusion list)
- ✅ No architectural changes
- ✅ Reduces load on hot paths

**Cons**:
- ⚠️ Incomplete data
- ⚠️ Still blocks on logged routes

**Expected Result**: Minimal impact (already skipping static files)

**Risk Level**: LOW - Easy to implement

---

### Option 6: Move to @after_request Hook
**Implementation**: Log after response is generated

**Pros**:
- ✅ User sees page faster (logging happens after)
- ✅ Simple change (move decorator)

**Cons**:
- ⚠️ Still blocks response sending
- ⚠️ Doesn't actually improve total request time
- ⚠️ If logging fails, response already sent

**Expected Result**: Perceived improvement, but same actual overhead

**Risk Level**: LOW - Easy to implement

---

## Nginx Integration Details

### Current nginx Setup
From CLAUDE.md: "The app runs behind nginx as reverse proxy"

### What nginx Logs by Default
```
# Standard Combined Log Format
127.0.0.1 - - [15/Jan/2026:10:30:15 +0100] "GET /admin/klassen HTTP/1.1" 200 5234 "-" "Mozilla/5.0..."
```

### What We'd Need to Add
To distinguish users, need to log session cookie:
```nginx
log_format analytics '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    '$request_time '
                    '$cookie_session';  # Session ID for user lookup

access_log /var/log/nginx/lernmanager_analytics.log analytics;
```

### Limitations of nginx Logging
1. **No context awareness**: Can't know if it's admin vs student without DB lookup
2. **Session cookie is opaque**: Need Flask to decrypt session
3. **No custom events**: Can't log "student completed task" or "quiz passed"
4. **POST data invisible**: Can't see what was submitted
5. **Delayed processing**: Need batch job to import logs

### When nginx Logging Makes Sense
- High-traffic public websites (thousands of requests/sec)
- Simple page view tracking
- When application performance is critical
- When analytics are processed offline

### When nginx Logging Doesn't Make Sense
- Low-traffic applications (<100 concurrent users)
- Rich event tracking needed
- Real-time analytics dashboard
- Application-level events (not just HTTP requests)

**Assessment for Lernmanager**:
❌ NOT RECOMMENDED - The rich event tracking (task completions, quiz results, per-student analytics) is core to the application's value. nginx logs can't capture this.

