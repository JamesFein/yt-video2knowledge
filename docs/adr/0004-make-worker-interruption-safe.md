# ADR-0004: Make worker interruption safe

**Date**: 2026-06-11
**Status**: proposed
**Deciders**: User, Codex

## Context

If the worker is interrupted while a digest is running, the system can be left in a false running state with a stale lock. That makes status output misleading and can prevent the next worker tick from safely continuing the unfinished request.

## Decision

When the worker receives `SIGTERM` or `SIGINT`, it records the current task as interrupted, transitions state away from `running`, releases the worker lock, preserves unfinished requests, and allows the next worker run to continue processing.

## Alternatives Considered

### Let the process die without cleanup
- **Pros**: No signal-handling code.
- **Cons**: Can leave stale locks and false running status.
- **Why not**: This is one of the core reliability failures the stability work addresses.

### Delete all state on next startup
- **Pros**: Simple recovery path.
- **Cons**: Risks losing unfinished requests or hiding the interrupted run.
- **Why not**: Recovery should preserve diagnosable state and pending work.

## Consequences

### Positive
- Status output can distinguish interrupted work from active work.
- The next worker run can safely resume unfinished requests.
- Operators do not need to guess whether a lock represents live work.

### Negative
- The worker needs explicit signal handling and cleanup ordering.
- Tests must simulate interruption without relying on real long-running processes.

### Risks
- Cleanup could remove another worker's live lock; mitigate by recording lock ownership and testing live-lock protection.

## Related

- [PRD](../../prd.md)
