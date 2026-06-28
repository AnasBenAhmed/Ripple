import asyncio
from collections.abc import AsyncGenerator

import httpx

from extractors.base import Format

READ_SIZE = 65536           # 64 KB streaming read size
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB Range chunks for YouTube CDN

_CDN_HEADERS = {"Accept-Encoding": "identity"}


async def stream_direct(url: str, extra_headers: dict | None = None) -> AsyncGenerator[bytes, None]:
    """Stream a direct URL. YouTube CDN uses sequential 10 MB Range chunks to avoid throttling."""
    import re

    base_headers = dict(extra_headers or {})

    if "googlevideo.com" not in url:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            async with client.stream("GET", url, headers=base_headers) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(READ_SIZE):
                    yield chunk
        return

    m = re.search(r'[?&]clen=(\d+)', url)
    clen = int(m.group(1)) if m else None

    async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
        if not clen:
            async with client.stream("GET", url, headers={**base_headers, **_CDN_HEADERS}) as r:
                r.raise_for_status()
                async for chunk in r.aiter_bytes(READ_SIZE):
                    yield chunk
            return

        pos = 0
        while pos < clen:
            end = min(pos + CHUNK_SIZE - 1, clen - 1)
            headers = {**base_headers, **_CDN_HEADERS, "Range": f"bytes={pos}-{end}"}
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.content
            for i in range(0, len(data), READ_SIZE):
                yield data[i:i + READ_SIZE]
            pos += len(data)


async def stream_audio_extract(fmt: Format) -> AsyncGenerator[bytes, None]:
    """Let ffmpeg fetch the URL directly and extract MP3 — no temp file, streams immediately."""
    url = fmt.direct_url or fmt.video_url
    extra_headers = fmt.http_headers or {}

    cmd = ["ffmpeg", "-y"]
    if extra_headers:
        header_str = "".join(f"{k}: {v}\r\n" for k, v in extra_headers.items())
        cmd += ["-headers", header_str]
    cmd += [
        "-i", url,
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "2",
        "-f", "mp3",
        "pipe:1",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    while True:
        chunk = await proc.stdout.read(READ_SIZE)
        if not chunk:
            break
        yield chunk
    await proc.wait()


async def stream_ffmpeg_url(url: str, audio_only: bool = False,
                            extra_headers: dict | None = None) -> AsyncGenerator[bytes, None]:
    """Use ffmpeg to download an HLS/M3U8 or any direct URL — handles segmented streams."""
    cmd = ["ffmpeg", "-y"]
    # Pass CDN headers to ffmpeg's HTTP client
    if extra_headers:
        hdr = "".join(f"{k}: {v}\r\n" for k, v in extra_headers.items())
        cmd += ["-headers", hdr]
    cmd += ["-i", url]
    if audio_only:
        cmd += ["-vn", "-acodec", "libmp3lame", "-q:a", "2", "-f", "mp3"]
    else:
        # aac_adtstoasc: converts ADTS AAC (MPEG-TS/HLS) to MPEG-4 AAC for MP4 muxing
        cmd += ["-c", "copy", "-bsf:a", "aac_adtstoasc", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4"]
    cmd += ["pipe:1"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    while True:
        chunk = await proc.stdout.read(READ_SIZE)
        if not chunk:
            break
        yield chunk
    await proc.wait()


async def stream_merged(fmt: Format) -> AsyncGenerator[bytes, None]:
    """ffmpeg pulls video+audio via local CDN proxy (Range chunks → fast) and muxes to browser."""
    import urllib.parse

    BASE = "http://localhost:8006"
    video_proxy = f"{BASE}/api/cdnproxy?url={urllib.parse.quote(fmt.video_url, safe='')}"
    audio_proxy = f"{BASE}/api/cdnproxy?url={urllib.parse.quote(fmt.audio_url, safe='')}"

    cmd = [
        "ffmpeg", "-y",
        "-i", video_proxy,
        "-i", audio_proxy,
        "-c", "copy",
        "-movflags", "frag_keyframe+empty_moov",
        "-f", "mp4",
        "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    while True:
        chunk = await proc.stdout.read(READ_SIZE)
        if not chunk:
            break
        yield chunk
    await proc.wait()
