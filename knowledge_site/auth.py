from __future__ import annotations

from urllib.parse import parse_qs, quote

from fastapi import HTTPException, Request
from starlette.responses import RedirectResponse


SESSION_AUTH_KEY = "authenticated"


def is_authenticated(request: Request) -> bool:
    return bool(request.session.get(SESSION_AUTH_KEY))


def login_redirect(request: Request) -> RedirectResponse:
    next_url = quote(request.url.path)
    return RedirectResponse(f"/login?next={next_url}", status_code=303)


def sanitize_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/"


async def read_urlencoded_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def require_api_auth(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Authentication required")

