# SQLCipher Removal (2026-02-23)

## Problem

Production load spikes: CPU 100%, ~30s response times, waitress queue depth 15–26 under class-size concurrent quiz load (~25 students submitting simultaneously).

## Root Cause

SQLCipher encrypts/decrypts every 4KB DB page individually. For a 2.38MB database (~600 pages), every cache miss under concurrent load triggers multiple AES operations on a single CPU core. The page cache cannot absorb burst requests — each concurrent request pays the full crypto cost.

This is a structural mismatch: SQLCipher is designed for single-user mobile/desktop use, not concurrent server workloads on constrained hardware.

## Fix

Switched production DB to plain SQLite via `deploy/db_crypto.py switch`.

## Benchmark (post-fix, 100 iterations, 1-core VPS)

| Metric | Result |
|---|---|
| DB queries | 0.4–0.6ms median |
| Admin pages | ~5ms median |
| Student dashboard | ~6ms median |
| Waitress queue warnings | 0 (over full lesson, full class) |

## Decision

**Plain SQLite in production permanently.**

If data-at-rest protection becomes a requirement, use OS-level disk encryption (LUKS/dm-crypt). The kernel handles it in the DMA path, transparent to the app, with no per-request overhead.

## Tools Left in Place

`deploy/db_crypto.py` with `switch`, `encrypt`, `decrypt`, `rekey`, `verify` operations — kept for emergency use or future re-evaluation.
