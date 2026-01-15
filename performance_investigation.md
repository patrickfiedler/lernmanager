# Task Plan: Activity Logging Performance Investigation

## Goal
Measure the performance impact of database-based activity logging and identify viable alternatives that maintain audit capabilities while reducing latency.

## Phases
- [x] Phase 1: Understand current implementation
- [x] Phase 2: Measure current performance impact
- [x] Phase 3: Research alternative approaches
- [x] Phase 4: Document findings and recommendations

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
**COMPLETE** - Investigation finished, recommendations documented

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

### Critical Recommendation
**URGENT: Enable SQLite WAL mode + synchronous=NORMAL**

Expected improvement: **84ms → 10-20ms** (70-75% reduction)
- WAL mode: Eliminates blocking disk syncs
- synchronous=NORMAL: Safe with WAL, much faster
- Still fully ACID-compliant and safe

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
