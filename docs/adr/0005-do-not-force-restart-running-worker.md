# ADR-0005: Do not force restart a running worker

**Date**: 2026-06-11
**Status**: proposed
**Deciders**: User, Codex

## Context

`launchctl kickstart -k` kills the old process before starting a new one. Using it while a digest worker is active can interrupt in-flight work and create exactly the stale status and lock states this stability work is meant to prevent.

## Decision

OpenClaw should enqueue digest requests and inspect worker status, not force-restart an active worker. Operators should enqueue the target date, inspect status, wait for the normal `launchd` tick, and only restart after confirming no worker is running.

## Alternatives Considered

### Force restart with `launchctl kickstart -k`
- **Pros**: Immediate and familiar when a service appears stuck.
- **Cons**: Can kill active digest work and leave partial state behind.
- **Why not**: It is unsafe for active long-running digest jobs.

### Make OpenClaw directly control worker lifecycle
- **Pros**: Gives the UI/tool more direct control.
- **Cons**: Couples request submission to process management and increases the chance of interrupting work.
- **Why not**: Queueing and status inspection are enough for this local workflow.

## Consequences

### Positive
- Reduces accidental interruption of active digest runs.
- Keeps OpenClaw's responsibility narrow: enqueue and observe.
- Encourages status-driven operations.

### Negative
- Operators may wait up to the configured `launchd` tick before work starts.
- Emergency restart remains a manual, status-gated operation.

### Risks
- Operators may still force restart out of habit; mitigate by documenting the safe procedure in runbooks and status output.

## Related

- [PRD](../../prd.md)
- [Knowledge Site deployment instructions](../agent-instructions/knowledge-site-deployment.md)
