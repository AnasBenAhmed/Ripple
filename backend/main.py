import re

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from services import router as media_router
from services.downloader import stream_merged, stream_direct, stream_audio_extract, stream_ffmpeg_url, stream_hls_audio_ytdlp
from extractors.base import Format

app = FastAPI(title="Ripple API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class InfoRequest(BaseModel):
    url: str


class FormatOut(BaseModel):
    id: str
    label: str
    ext: str
    thumbnail: str | None = None


class InfoResponse(BaseModel):
    title: str
    thumbnail: str
    platform: str
    formats: list[FormatOut]
    duration: int | None = None


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/info", response_model=InfoResponse)
async def info(body: InfoRequest):
    try:
        media = await media_router.get_info(body.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {e}")

    return InfoResponse(
        title=media.title,
        thumbnail=media.thumbnail,
        platform=media.platform,
        formats=[FormatOut(id=f.id, label=f.label, ext=f.ext, thumbnail=f.thumbnail) for f in media.formats],
        duration=media.duration,
    )


@app.get("/api/thumbnail")
async def thumbnail_proxy(url: str = Query(...)):
    """Proxy thumbnails that require a Referer or block cross-origin image loads."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            r = await client.get(url, headers={"Referer": "https://www.instagram.com/"})
            r.raise_for_status()
            return Response(
                content=r.content,
                media_type=r.headers.get("content-type", "image/jpeg"),
            )
    except Exception:
        raise HTTPException(status_code=502, detail="Could not fetch thumbnail")


async def _head_filesize(url: str, extra_headers: dict) -> int | None:
    """Try a HEAD request to get Content-Length. Returns None on any failure."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
            r = await client.head(url, headers=extra_headers)
            cl = r.headers.get("content-length", "")
            return int(cl) if cl.isdigit() else None
    except Exception:
        return None


@app.get("/api/download")
async def download(
    url: str = Query(...),
    format_id: str = Query(...),
):
    try:
        media = await media_router.get_info(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    fmt: Format | None = next((f for f in media.formats if f.id == format_id), None)
    if not fmt:
        raise HTTPException(status_code=404, detail=f"Format '{format_id}' not found")

    # Strip non-ASCII and control chars (newlines in captions break HTTP headers)
    ascii_title = media.title.encode("ascii", errors="ignore").decode("ascii")
    ascii_title = re.sub(r'[\r\n\t]', ' ', ascii_title)
    safe_title = re.sub(r'[^\w -]', '', ascii_title).strip().replace(" ", "_")[:80] or "download"
    filename = f"{safe_title}.{fmt.ext}"

    if fmt.ext == "mp3":
        media_type = "audio/mpeg"
    elif fmt.ext == "jpg":
        media_type = "image/jpeg"
    else:
        media_type = "video/mp4"

    cdn_headers = fmt.http_headers or {}

    # Resolve Content-Length so browsers show download progress
    filesize: int | None = fmt.filesize
    if filesize is None and not fmt.needs_audio_extract:
        if not fmt.is_hls:
            direct = fmt.direct_url or fmt.audio_url or fmt.video_url
            if direct:
                filesize = await _head_filesize(direct, cdn_headers)

    response_headers: dict = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if filesize:
        response_headers["Content-Length"] = str(filesize)

    if fmt.needs_merge:
        return StreamingResponse(
            content=stream_merged(fmt),
            media_type=media_type,
            headers=response_headers,
        )
    elif fmt.needs_audio_extract:
        return StreamingResponse(
            content=stream_audio_extract(fmt),
            media_type=media_type,
            headers=response_headers,
        )
    elif fmt.is_hls:
        if fmt.ext == "mp3":
            # yt-dlp --concurrent-fragments downloads 4 segments simultaneously,
            # eliminating the serial RTT overhead that kills speed on high-latency connections
            return StreamingResponse(
                content=stream_hls_audio_ytdlp(url),
                media_type=media_type,
                headers=response_headers,
            )
        else:
            direct_url = fmt.direct_url or fmt.audio_url or fmt.video_url
            return StreamingResponse(
                content=stream_ffmpeg_url(direct_url, audio_only=False, extra_headers=cdn_headers),
                media_type=media_type,
                headers=response_headers,
            )
    else:
        direct_url = fmt.direct_url or fmt.audio_url or fmt.video_url
        return StreamingResponse(
            content=stream_direct(direct_url, cdn_headers),
            media_type=media_type,
            headers=response_headers,
        )
