# ADR-0003: Bound pending summary retries

**Date**: 2026-06-11
**Status**: proposed
**Deciders**: User, Codex

## Context

Temporary LLM/API failures such as `IncompleteRead`, empty responses, and bad responses can leave individual videos in `pending_summary`. Retrying the whole day wastes work that has already succeeded, while retrying forever can consume API budget and keep the run permanently unfinished.

## Decision

We retry only the failed or pending summary steps, not already successful videos or the entire day. Retries are bounded by attempt count, elapsed time, and non-retriable error classification; after the stop condition, the video remains diagnosable as `needs_review` or error-bearing `pending_summary`.

## Alternatives Considered

### Rerun the full target date
- **Pros**: Simple operator model.
- **Cons**: Reprocesses successful videos and makes partial failures more expensive.
- **Why not**: The manifest can identify the exact videos that need retry.

### Retry forever
- **Pros**: Maximizes the chance of eventual automatic success.
- **Cons**: Can burn API calls and keep a run in limbo.
- **Why not**: The workflow needs bounded automation and clear handoff to review.

### Manual retry only
- **Pros**: Avoids automatic API spend.
- **Cons**: Makes transient failures noisy and increases operator burden.
- **Why not**: Common temporary failures should recover without manual intervention.

## Consequences

### Positive
- Preserves successful summaries.
- Reduces wasted API calls and elapsed time.
- Produces clear states for retry, partial success, and human review.

### Negative
- Requires tracking attempts, last error, and timing.
- Requires distinguishing retriable from non-retriable failures.

### Risks
- Error classification may be imperfect; mitigate by starting with a small explicit set of retriable and non-retriable cases and keeping the final state diagnosable.

## Related

- [PRD](../../prd.md)
