import asyncio
import re

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from services import router as media_router
from services.downloader import READ_SIZE, CHUNK_SIZE, _CDN_HEADERS, stream_merged, stream_direct, stream_audio_extract, stream_ffmpeg_url, stream_hls_concurrent, stream_hls_mp3_parallel
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
    filesize: int | None = None


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
        formats=[FormatOut(id=f.id, label=f.label, ext=f.ext, thumbnail=f.thumbnail, filesize=f.filesize) for f in media.formats],
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


@app.get("/api/cdnproxy")
async def cdn_proxy(url: str = Query(...)):
    """Proxy YouTube CDN URLs using 10 MB Range chunks to bypass per-connection throttling.
    ffmpeg connects here (localhost, fast) instead of CDN directly (throttled)."""
    m = re.search(r'[?&]clen=(\d+)', url)
    clen = int(m.group(1)) if m else None

    async def stream():
        base = dict(_CDN_HEADERS)
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            if not clen:
                async with client.stream("GET", url, headers=base) as r:
                    r.raise_for_status()
                    async for chunk in r.aiter_bytes(READ_SIZE):
                        yield chunk
                return
            pos = 0
            while pos < clen:
                end = min(pos + CHUNK_SIZE - 1, clen - 1)
                # YouTube CDN throttling sometimes returns a transient 403; retry the chunk.
                for attempt in range(4):
                    r = await client.get(url, headers={**base, "Range": f"bytes={pos}-{end}"})
                    if r.status_code in (403, 503) and attempt < 3:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    break
                data = r.content
                for i in range(0, len(data), READ_SIZE):
                    yield data[i:i + READ_SIZE]
                pos += len(data)

    headers = {"Content-Length": str(clen)} if clen else {}
    return StreamingResponse(stream(), media_type="application/octet-stream", headers=headers)


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
    elif fmt.ext == "m4a":
        media_type = "audio/mp4"
    elif fmt.ext == "jpg":
        media_type = "image/jpeg"
    else:
        media_type = "video/mp4"

    cdn_headers = fmt.http_headers or {}

    # Resolve Content-Length so browsers show download progress.
    # Merged streams (ffmpeg mux) produce output that differs from raw CDN clen sum —
    # sending wrong Content-Length causes browsers to report "network error".
    filesize: int | None = None
    if not fmt.needs_merge and not fmt.needs_audio_extract and not fmt.is_hls:
        filesize = fmt.filesize
        if filesize is None:
            direct = fmt.direct_url or fmt.audio_url or fmt.video_url
            if direct:
                filesize = await _head_filesize(direct, cdn_headers)

    response_headers: dict = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if filesize:
        response_headers["Content-Length"] = str(filesize)

    if fmt.needs_merge:
        content = stream_merged(fmt)  # ffmpeg fetches CDN URLs + muxes inline
    elif fmt.needs_audio_extract:
        content = stream_audio_extract(fmt)
    elif fmt.is_hls:
        direct_url = fmt.direct_url or fmt.audio_url or fmt.video_url
        if fmt.ext == "mp3":
            # MP3 transcode is CPU-bound — encode fragment batches across cores in parallel.
            content = stream_hls_mp3_parallel(direct_url, extra_headers=cdn_headers)
        else:
            # M4A copies audio; MP4 muxes video — both download fragments in parallel.
            content = stream_hls_concurrent(direct_url, audio_only=fmt.ext == "m4a", extra_headers=cdn_headers)
    else:
        direct_url = fmt.direct_url or fmt.audio_url or fmt.video_url
        content = stream_direct(direct_url, cdn_headers)

    return StreamingResponse(
        content=content,
        media_type=media_type,
        headers=response_headers,
    )
