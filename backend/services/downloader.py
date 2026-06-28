import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator

import httpx

from extractors.base import Format

# yt-dlp uses 10 MB chunks for YouTube CDN (http_chunk_size = 10 << 20)
CHUNK_SIZE = 10 * 1024 * 1024
READ_SIZE  = 65536  # 64 KB streaming read size

# yt-dlp disables content-encoding on CDN requests so Range byte offsets stay accurate
_CDN_HEADERS = {"Accept-Encoding": "identity"}


async def _download_chunked(url: str, extra_headers: dict | None = None) -> bytes:
    """Download a URL using sequential 10 MB Range requests (yt-dlp's http_chunk_size approach)."""
    import re
    base = dict(extra_headers or {})
    m = re.search(r'[?&]clen=(\d+)', url)
    clen = int(m.group(1)) if m else None

    async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
        if not clen:
            r = await client.get(url, headers={**base, **_CDN_HEADERS})
            r.raise_for_status()
            return r.content

        parts: list[bytes] = []
        pos = 0
        while pos < clen:
            end = min(pos + CHUNK_SIZE - 1, clen - 1)
            headers = {**base, **_CDN_HEADERS, "Range": f"bytes={pos}-{end}"}
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            chunk = r.content
            parts.append(chunk)
            pos += len(chunk)

    return b"".join(parts)


async def stream_direct(url: str, extra_headers: dict | None = None) -> AsyncGenerator[bytes, None]:
    """Stream a direct URL. YouTube CDN uses sequential 10 MB Range chunks like yt-dlp."""
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


async def stream_hls_audio_ytdlp(url: str) -> AsyncGenerator[bytes, None]:
    """Download HLS with yt-dlp (4 concurrent fragments) then convert to MP3 via ffmpeg.
    Must use os.pipe() file descriptors — asyncio StreamReader cannot be used as subprocess stdin."""
    r_fd, w_fd = os.pipe()

    yt_proc = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "--concurrent-fragments", "4",
        "-f", "worst",
        "--no-warnings", "--quiet",
        "-o", "-",
        url,
        stdout=w_fd,
        stderr=asyncio.subprocess.DEVNULL,
    )
    os.close(w_fd)  # parent doesn't write; close so ffmpeg sees EOF when yt-dlp exits

    ff_proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-i", "pipe:0",
        "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        "-f", "mp3", "pipe:1",
        stdin=r_fd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    os.close(r_fd)  # transferred to ffmpeg; parent closes its copy

    while True:
        chunk = await ff_proc.stdout.read(READ_SIZE)
        if not chunk:
            break
        yield chunk

    await asyncio.gather(yt_proc.wait(), ff_proc.wait())


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


async def stream_merged(fmt: Format, request_headers: dict | None = None) -> AsyncGenerator[bytes, None]:
    """Download video+audio simultaneously (parallel tasks), merge with ffmpeg, stream MP4."""
    h = fmt.http_headers or {}
    video_data, audio_data = await asyncio.gather(
        _download_chunked(fmt.video_url, h),
        _download_chunked(fmt.audio_url, h),
    )

    vf = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    af = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
    try:
        vf.write(video_data)
        vf.close()
        af.write(audio_data)
        af.close()

        cmd = [
            "ffmpeg", "-y",
            "-i", vf.name,
            "-i", af.name,
            "-c:v", "copy",
            "-c:a", "aac",
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
    finally:
        vf_name = vf.name
        af_name = af.name
        if os.path.exists(vf_name):
            os.unlink(vf_name)
        if os.path.exists(af_name):
            os.unlink(af_name)
