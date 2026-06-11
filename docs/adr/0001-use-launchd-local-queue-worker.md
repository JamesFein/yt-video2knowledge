# ADR-0001: Use launchd and local queue worker instead of Celery

**Date**: 2026-06-11
**Status**: proposed
**Deciders**: User, Codex

## Context

The digest workflow is local-first, single-machine, and expected to run once per day. The current reliability issues are around retries, status reporting, interruption handling, and lock recovery. Those problems can be addressed in the existing worker without adding a distributed task system.

## Decision

We keep the existing `launchd + local queue worker` architecture and do not introduce Celery for this stability work. The worker should become more reliable by improving retry behavior, status state, lock metadata, and recovery paths.

## Alternatives Considered

### Celery with a broker
- **Pros**: Built-in task queue concepts, retry primitives, and worker separation.
- **Cons**: Adds broker operation, more moving parts, and more failure modes for a single-machine workflow.
- **Why not**: The current problem does not require distributed workers or a broker.

### Manual digest scripts only
- **Pros**: Simplest operational surface.
- **Cons**: Pushes retry, status, and interruption handling back onto the operator.
- **Why not**: The workflow needs unattended daily execution with observable recovery.

## Consequences

### Positive
- Keeps the local setup small and understandable.
- Avoids introducing broker deployment, monitoring, and recovery work.
- Focuses the implementation on the known failure modes.

### Negative
- The local worker must own retry, lock, and status logic explicitly.
- This does not prepare the system for multi-machine processing.

### Risks
- Local worker logic can become too complex; mitigate with focused unit and integration tests around retry, status, and lock recovery.

## Related

- [PRD](../../prd.md)
