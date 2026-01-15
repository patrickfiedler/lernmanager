# Task Plan: Activity Logging Performance Investigation

## Goal
Measure the performance impact of database-based activity logging and identify viable alternatives that maintain audit capabilities while reducing latency.

## Phases
- [x] Phase 1: Understand current implementation
- [x] Phase 2: Measure current performance impact
- [x] Phase 3: Research alternative approaches
- [x] Phase 4: Document findings and recommendations
- [x] Phase 5: Implement and test WAL mode (result: no improvement)
- [ ] Phase 6: Design async logging solution
- [ ] Phase 7: Implement async logging
- [ ] Phase 8: Test and verify improvement

## Key Questions
1. ✓ How is activity logging currently implemented? - Synchronous @before_request hook
2. ✓ Is it synchronous or asynchronous? - SYNCHRONOUS (blocking)
3. ✓ What's the actual performance cost (ms per request)? - ~10ms average
4. ✓ What alternatives exist? - WAL mode, async queue, nginx logs, hybrid, etc.
5. ✓ What are the tradeoffs? - See performance_notes.md and logging_recommendations.md

## Decisions Made
- None yet

## Errors Encountered
- None yet

## Status
**Phase 7: Async Logging IMPLEMENTED** - Testing shows 99.1% improvement (10ms → 0.09ms)

## Summary

### Key Findings - Local vs Production

**Local Development (unencrypted)**:
- Overhead: ~10ms per request
- Configuration: synchronous=FULL, journal_mode=DELETE

**Production VPS (SQLCipher encrypted)**:
- ⚠️ Overhead: **~84ms per request** (8.4x worse than local!)
- Configuration: synchronous=FULL, journal_mode=DELETE
- Encryption enabled: Adds 1-2ms (minor compared to journal overhead)
- **HIGH IMPACT**: Users experience significant delays on every page load

### Root Cause Analysis
1. **Primary issue**: `synchronous=FULL` + `journal_mode=DELETE` = disk fsync on every write
2. **Encryption**: Adds minimal overhead (~1-2ms), not the bottleneck
3. **VPS disk I/O**: Much slower than local SSD (likely cloud storage backend)
4. **Impact**: 84ms added to EVERY authenticated page view

### WAL Mode Test Results (IMPLEMENTED)
**Result**: WAL mode did NOT improve performance on production VPS

**After enabling WAL + synchronous=NORMAL**:
- Before: 83.86ms per request
- After: 85.81ms per request (essentially unchanged)
- WAL mode is confirmed active: `journal_mode: wal`, `synchronous: 1 (NORMAL)`

**Conclusion**: The bottleneck is the VPS disk I/O itself, not SQLite's journaling strategy. Even with WAL's optimizations, the underlying cloud storage is too slow for synchronous writes.

### Async Logging Implementation (COMPLETED)
**Strategy A: All Events Async - Implemented and Tested**

Since disk I/O is fundamentally slow (~85ms), we moved logging off the request path entirely:
- **Measured improvement (local)**: 10ms → 0.09ms (99.1% reduction)
- **Expected improvement (production)**: 85ms → <1ms (98.8% reduction)
- Logging happens in background thread, pages don't wait
- Small risk: events could be lost if crash occurs before write (<1 sec window)

**Implementation Details**:
- New module: `analytics_queue.py` (~200 lines)
- Thread-safe queue (maxsize=1000)
- Background worker thread with batch writes (up to 10 events)
- Graceful shutdown with queue flush
- Modified `models.log_analytics_event()` to enqueue instead of write
- Worker starts automatically in `init_app()`

**Files Modified**:
- `analytics_queue.py` (NEW) - Queue and worker implementation
- `models.py` - Changed `log_analytics_event()` to use queue
- `app.py` - Added worker startup in `init_app()`

### nginx Logging Assessment
**NOT RECOMMENDED** - Would lose rich event tracking (task completions, quiz results, student analytics) which is core to the application's value. The 10ms overhead is worth it.

### Next Steps
1. Review `logging_recommendations.md` for detailed implementation guide
2. Implement WAL mode (5-minute change in models.py)
3. Test and measure improvement
4. Consider async logging only if more improvement needed

### Files Created
- `performance_notes.md` - Detailed technical findings
- `logging_recommendations.md` - Implementation guide and decision matrix
- `benchmark_logging.py` - Performance measurement tool
