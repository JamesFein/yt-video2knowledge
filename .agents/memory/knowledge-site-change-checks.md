# Knowledge Site Change Checks

When touching Knowledge Site rendering, parsing, or deployment:

- Use real `data/runs` samples before trusting toy fixtures.
- Remove only the proven duplicate, never the content-bearing heading.
- After Python changes, restart non-`--reload` Uvicorn before judging UI.
- Verify the public `miniaiheadlines.top` path, especially when cookies/Tunnel are involved.

Bias: short rule, real page, running process, public path.
