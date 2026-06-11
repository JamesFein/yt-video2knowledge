# ADR-0002: Use manifest as completion authority

**Date**: 2026-06-11
**Status**: proposed
**Deciders**: User, Codex

## Context

A digest process can exit successfully while some videos remain in `pending_summary`. Treating process exit code as the only success signal can hide partial business failure and report a run as complete when the manifest says work remains.

## Decision

We use the run manifest as the authority for digest completion. A target date is complete only when the manifest reports `failed_count = 0` and `pending_summary_count = 0`; exit code `0` with pending summaries is partial success that requires retry or review.

## Alternatives Considered

### Process exit code only
- **Pros**: Easy to check and already produced by the process.
- **Cons**: Cannot distinguish complete success from partial digest output.
- **Why not**: It can report success while summaries are still pending.

### Presence of output files
- **Pros**: Simple filesystem-based check.
- **Cons**: Does not reliably express per-video state or counts.
- **Why not**: The manifest already contains the structured state needed by status and retry logic.

## Consequences

### Positive
- User-facing status matches the actual digest result.
- Retry logic can target only incomplete work.
- Regression tests can assert completion through stable manifest fields.

### Negative
- Worker and status code must parse and trust manifest contents.
- Missing or malformed manifests need a clear non-success state.

### Risks
- Manifest schema drift could break completion checks; mitigate by keeping tests close to the fields used for completion.

## Related

- [PRD](../../prd.md)
