---
status: temporary
last_verified: 2026-06-19
---

# Captured Rules - Pending Review

Rules automatically captured from conversations. Review and promote to permanent storage.

---

## Pending Rules

None.

---

## Processed Rules

### [2026-06-19 19:15] - Workflow: Service Restart Preflight

**User said:**

> "總結剛才你在操作中犯下的錯誤,然後思考下一次怎麼樣永久地避免這些錯誤的存在。"

**Rule extracted:**

- **Type**: ALWAYS
- **Action**: Before stopping or restarting a running service, first confirm all required restart inputs are available, including environment variables, secrets, credentials, config files, current process owner, and the intended process manager.
- **Context**: Applies to Knowledge Site deployment work and any task that changes long-running background services.
- **Category**: workflow

**Status**: PROCESSED

**Promoted to:** `docs/agents/knowledge-site-deployment.md`

### [2026-06-19 19:15] - Workflow: Service Verification Must Match App Behavior

**User said:**

> "總結剛才你在操作中犯下的錯誤,然後思考下一次怎麼樣永久地避免這些錯誤的存在。"

**Rule extracted:**

- **Type**: ALWAYS
- **Action**: Verify a restarted web service with a request method and expected status that the app actually supports, then interpret the result against that contract.
- **Context**: Applies when validating FastAPI/Knowledge Site availability or any web app after restart.
- **Category**: workflow

**Status**: PROCESSED

**Promoted to:** `docs/agents/knowledge-site-deployment.md`

### [2026-06-19 19:15] - Workflow: Background Process Persistence Check

**User said:**

> "總結剛才你在操作中犯下的錯誤,然後思考下一次怎麼樣永久地避免這些錯誤的存在。"

**Rule extracted:**

- **Type**: ALWAYS
- **Action**: After starting a background service, wait briefly and re-check exact port listeners, exact process identity, and the selected process manager before reporting success.
- **Context**: Applies to Uvicorn, cloudflared, local servers, and any background process started for the user.
- **Category**: workflow

**Status**: PROCESSED

**Promoted to:** `docs/agents/knowledge-site-deployment.md`

### [2026-06-19 19:15] - Tools: Exact Process Matching

**User said:**

> "總結剛才你在操作中犯下的錯誤,然後思考下一次怎麼樣永久地避免這些錯誤的存在。"

**Rule extracted:**

- **Type**: ALWAYS
- **Action**: Use exact process and port checks for service operations; avoid broad `ps | rg`, `pgrep -f`, or `pkill -f` patterns that can match logs, shell commands, or prior agent messages.
- **Context**: Applies when inspecting or stopping Uvicorn, cloudflared, and other long-running local services.
- **Category**: tools

**Status**: PROCESSED

**Promoted to:** `docs/agents/knowledge-site-deployment.md`
