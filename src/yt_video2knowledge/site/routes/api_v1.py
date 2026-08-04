from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from yt_video2knowledge.site.auth import require_api_auth
from yt_video2knowledge.site.database import connect_db, utc_now


router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_api_auth)],
)


class MetaSummaryIn(BaseModel):
    content: str


@router.get("/videos/{video_id}/meta-summary")
def get_meta_summary(video_id: str, request: Request) -> dict[str, str | None]:
    conn = connect_db(request.app.state.settings.db_path)
    try:
        row = _fetch_meta_summary(conn, video_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return dict(row)


@router.put("/videos/{video_id}/meta-summary")
def put_meta_summary(
    video_id: str,
    payload: MetaSummaryIn,
    request: Request,
) -> dict[str, str | None]:
    conn = connect_db(request.app.state.settings.db_path)
    try:
        with conn:
            video = conn.execute(
                "SELECT video_id FROM videos WHERE video_id = ?",
                (video_id,),
            ).fetchone()
            if video is None:
                raise HTTPException(status_code=404, detail="Video not found")
            conn.execute(
                """
                INSERT INTO video_meta_summaries (video_id, content, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (video_id, payload.content, utc_now()),
            )
        row = _fetch_meta_summary(conn, video_id)
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return dict(row)


def _fetch_meta_summary(conn, video_id: str):
    return conn.execute(
        """
        SELECT
            v.video_id,
            COALESCE(m.content, '') AS content,
            m.updated_at
        FROM videos AS v
        LEFT JOIN video_meta_summaries AS m ON m.video_id = v.video_id
        WHERE v.video_id = ?
        """,
        (video_id,),
    ).fetchone()
