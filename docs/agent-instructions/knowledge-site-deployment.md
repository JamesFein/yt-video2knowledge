# Knowledge Site Deployment Rules

## When To Read

Read this before changing Knowledge Site code, running tests that touch the app, starting or stopping the FastAPI server, or working with Cloudflare Tunnel.

## Required Harness

- Before starting the Knowledge Site, check for existing app and tunnel state:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
pgrep -x cloudflared || true
screen -ls | sed -n '/knowledge-site/p' || true
```

- If a restart is needed, stop only the exact deployment processes:

```bash
kill $(lsof -tiTCP:8000 -sTCP:LISTEN) 2>/dev/null || true
kill $(pgrep -x cloudflared) 2>/dev/null || true
screen -S knowledge-site-uvicorn -X quit 2>/dev/null || true
screen -S knowledge-site-cloudflared -X quit 2>/dev/null || true
```

- Do not use broad `pkill -f cloudflared`, `pgrep -f cloudflared`, or `pkill -f 8000` cleanup. Tooling, logs, or prior agent messages can contain those strings and cause false matches.
- After code changes and tests, leave one explicit final state:
  - stopped: no listener on `127.0.0.1:8000` and no exact `cloudflared` process; or
  - running: exactly one Uvicorn/FastAPI listener on `127.0.0.1:8000` and exactly one `cloudflared tunnel run` named connector.

## Fixed Domain Rules

- Fixed-domain deployment uses the named tunnel for `miniaiheadlines.top` and `www.miniaiheadlines.top`, both pointing to `http://127.0.0.1:8000`.
- Prefer `cloudflared tunnel run` with `TUNNEL_TOKEN` or a temporary token file. Do not write Cloudflare tokens, Knowledge Site passwords, or session secrets to repo files, docs, shell history, final answers, or process command lines.
- Quick Tunnel (`cloudflared tunnel --url http://127.0.0.1:8000`) is only for temporary testing. Stop it before restoring fixed-domain named tunnel service.
- If fixed domains return Cloudflare `530`, treat Cloudflare as reachable but the local connector/origin as unavailable. Check `127.0.0.1:8000` first, then the exact `cloudflared` named connector.

## Verification

- Local app verification must use `GET`, not `HEAD`; this app can return `405` for `HEAD /`.

```bash
curl -sS -o /tmp/knowledge-site-local.html -w '%{http_code}\n' --max-time 5 http://127.0.0.1:8000/
```

- Expected unauthenticated local and fixed-domain responses are `303` redirects to the login flow.

```bash
curl -sS -o /tmp/knowledge-site-root.html -w '%{http_code}\n' --max-time 10 https://miniaiheadlines.top/
curl -sS -o /tmp/knowledge-site-www.html -w '%{http_code}\n' --max-time 10 https://www.miniaiheadlines.top/
```

- Final process check:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN || true
ps axww -o pid=,comm=,args= | awk '$2 ~ /(^|\/)cloudflared$/ {print}'
screen -ls | sed -n '/knowledge-site/p' || true
```
