from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse

from knowledge_site.auth import (
    SESSION_AUTH_KEY,
    is_authenticated,
    login_redirect,
    read_urlencoded_form,
    sanitize_next,
)
from knowledge_site.database import connect_db
from knowledge_site.markdown_blocks import markdown_to_plain_text, split_markdown_blocks


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> HTMLResponse:
    if is_authenticated(request):
        return RedirectResponse(sanitize_next(next), status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": sanitize_next(next), "error": None},
    )


@router.post("/login", response_class=HTMLResponse)
async def login(request: Request) -> HTMLResponse:
    form = await read_urlencoded_form(request)
    settings = request.app.state.settings
    next_url = sanitize_next(form.get("next"))
    if form.get("password") == settings.password:
        request.session[SESSION_AUTH_KEY] = True
        return RedirectResponse(next_url, status_code=303)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": next_url, "error": "密码不正确"},
        status_code=401,
    )


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    redirect = _require_login(request)
    if redirect:
        return redirect

    conn = connect_db(request.app.state.settings.db_path)
    try:
        rows = conn.execute(
            """
            SELECT
                d.day_date,
                d.daily_summary_markdown,
                d.synced_at,
                COUNT(dv.video_id) AS video_count
            FROM days AS d
            LEFT JOIN day_videos AS dv ON dv.day_date = d.day_date
            GROUP BY d.day_date
            ORDER BY d.day_date DESC
            """
        ).fetchall()
    finally:
        conn.close()

    days = [
        {
            **dict(row),
            "summary_excerpt": _excerpt(row["daily_summary_markdown"]),
        }
        for row in rows
    ]
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"days": days},
    )


@router.get("/days/{day_date}", response_class=HTMLResponse)
def day_detail(day_date: str, request: Request) -> HTMLResponse:
    redirect = _require_login(request)
    if redirect:
        return redirect

    conn = connect_db(request.app.state.settings.db_path)
    try:
        day = conn.execute(
            "SELECT * FROM days WHERE day_date = ?",
            (day_date,),
        ).fetchone()
        if day is None:
            raise HTTPException(status_code=404, detail="Day not found")
        videos = conn.execute(
            """
            SELECT v.*
            FROM day_videos AS dv
            JOIN videos AS v ON v.video_id = dv.video_id
            WHERE dv.day_date = ?
            ORDER BY dv.position ASC, v.title ASC
            """,
            (day_date,),
        ).fetchall()
    finally:
        conn.close()

    return templates.TemplateResponse(
        request=request,
        name="day.html",
        context={
            "day": dict(day),
            "day_summary_text": markdown_to_plain_text(day["daily_summary_markdown"]),
            "videos": [dict(video) for video in videos],
        },
    )


@router.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail(video_id: str, request: Request) -> HTMLResponse:
    redirect = _require_login(request)
    if redirect:
        return redirect

    conn = connect_db(request.app.state.settings.db_path)
    try:
        video = conn.execute(
            """
            SELECT
                v.*,
                COALESCE(m.content, '') AS meta_content,
                m.updated_at AS meta_updated_at
            FROM videos AS v
            LEFT JOIN video_meta_summaries AS m ON m.video_id = v.video_id
            WHERE v.video_id = ?
            """,
            (video_id,),
        ).fetchone()
        if video is None:
            raise HTTPException(status_code=404, detail="Video not found")
    finally:
        conn.close()

    settings = request.app.state.settings
    video_dict = dict(video)
    video_dict["thumbnail_url"] = _asset_url(settings, video_dict.get("thumbnail_path"))
    return templates.TemplateResponse(
        request=request,
        name="video.html",
        context={
            "video": video_dict,
            "blocks": split_markdown_blocks(video["summary_markdown"]),
        },
    )


def _require_login(request: Request) -> RedirectResponse | None:
    if is_authenticated(request):
        return None
    return login_redirect(request)


def _excerpt(markdown: str, limit: int = 180) -> str:
    text = markdown_to_plain_text(markdown)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _asset_url(settings, value: str | None) -> str | None:
    if not value:
        return None
    asset_root = settings.assets_dir.resolve()
    try:
        relative_asset_root = asset_root.relative_to(settings.root_dir.resolve()).as_posix()
    except ValueError:
        return None
    prefix = relative_asset_root + "/"
    if value == relative_asset_root:
        return "/assets"
    if value.startswith(prefix):
        return "/assets/" + value[len(prefix) :]
    return None
