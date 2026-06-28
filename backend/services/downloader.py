import asyncio
import re
from collections.abc import AsyncGenerator
from urllib.parse import urljoin

import httpx

from extractors.base import Format

READ_SIZE = 65536           # 64 KB streaming read size
CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB Range chunks for YouTube CDN
HLS_CONCURRENCY = 8         # parallel HLS fragment downloads

_CDN_HEADERS = {"Accept-Encoding": "identity"}


async def _pump(proc) -> AsyncGenerator[bytes, None]:
    """Yield an ffmpeg subprocess's stdout, killing it if the client disconnects.

    The kill is synchronous so it still runs when the generator is closed under
    cancellation (an await in the finally could re-raise CancelledError first).
    """
    try:
        while True:
            chunk = await proc.stdout.read(READ_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass


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
    async for chunk in _pump(proc):
        yield chunk


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
    async for chunk in _pump(proc):
        yield chunk


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
    async for chunk in _pump(proc):
        yield chunk


def _parse_hls_segments(playlist: str, playlist_url: str) -> tuple[str | None, list[str]]:
    """Return (init_segment_url, [fragment_urls]) from a media playlist."""
    init: str | None = None
    frags: list[str] = []
    for line in playlist.splitlines():
        line = line.strip()
        if line.startswith("#EXT-X-MAP:"):
            m = re.search(r'URI="([^"]+)"', line)
            if m:
                init = urljoin(playlist_url, m.group(1))
        elif line and not line.startswith("#"):
            frags.append(urljoin(playlist_url, line))
    return init, frags


async def stream_hls_concurrent(playlist_url: str, audio_only: bool = False,
                                extra_headers: dict | None = None) -> AsyncGenerator[bytes, None]:
    """Download HLS fragments in parallel and pipe them to ffmpeg in order.

    Replaces ffmpeg's built-in (serial) HLS fetch — the serial RTT per fragment
    is what made long VOD audio/video downloads crawl. ffmpeg only muxes/encodes.
    """
    base_headers = {**(extra_headers or {}), **_CDN_HEADERS}

    async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
        r = await client.get(playlist_url, headers=base_headers)
        r.raise_for_status()
        init, frags = _parse_hls_segments(r.text, str(r.url))

    urls = ([init] if init else []) + frags
    if not urls:
        # Not a media playlist (or empty) — let ffmpeg handle the URL directly.
        async for chunk in stream_ffmpeg_url(playlist_url, audio_only, extra_headers):
            yield chunk
        return

    if audio_only:
        ff_args = ["-vn", "-acodec", "libmp3lame", "-q:a", "2", "-f", "mp3"]
    else:
        ff_args = ["-c", "copy", "-bsf:a", "aac_adtstoasc",
                   "-movflags", "frag_keyframe+empty_moov", "-f", "mp4"]
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", "pipe:0", *ff_args, "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    async def _feed():
        """Fetch fragments with a bounded look-ahead window, write to ffmpeg in order."""
        async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
            async def fetch(u: str) -> bytes:
                for attempt in range(3):
                    try:
                        resp = await client.get(u, headers=base_headers)
                        resp.raise_for_status()
                        return resp.content
                    except httpx.HTTPError:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(0.4)
                return b""

            window = HLS_CONCURRENCY * 2
            total = len(urls)
            tasks: dict[int, asyncio.Task] = {
                i: asyncio.create_task(fetch(urls[i])) for i in range(min(window, total))
            }
            try:
                for i in range(total):
                    data = await tasks.pop(i)
                    nxt = i + window
                    if nxt < total:
                        tasks[nxt] = asyncio.create_task(fetch(urls[nxt]))
                    proc.stdin.write(data)
                    await proc.stdin.drain()
            finally:
                for t in tasks.values():
                    t.cancel()
                proc.stdin.close()

    feeder = asyncio.create_task(_feed())
    try:
        while True:
            chunk = await proc.stdout.read(READ_SIZE)
            if not chunk:
                break
            yield chunk
    finally:
        # On client disconnect this runs under cancellation, so do the synchronous
        # kill FIRST — any await here may immediately re-raise CancelledError.
        feeder.cancel()
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
