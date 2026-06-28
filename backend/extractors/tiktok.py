import asyncio
import json
import os
import tempfile

from .base import BaseExtractor, Format, MediaInfo


def _parse_netscape_cookies(path: str) -> dict[str, str]:
    """Parse a Netscape cookie file into {name: value}."""
    cookies: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    cookies[parts[5]] = parts[6]
    except FileNotFoundError:
        pass
    return cookies


class TikTokExtractor(BaseExtractor):
    def match(self, url: str) -> bool:
        return "tiktok.com" in url

    async def extract_info(self, url: str) -> MediaInfo:
        cookie_file = os.path.join(tempfile.gettempdir(), "ripple_tiktok_cookies.txt")

        # yt-dlp handles TikTok's WAF challenge; --cookies makes it dump session cookies
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--dump-json", "--no-download", "--quiet", "--no-warnings",
            "--cookies", cookie_file,
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.TimeoutError:
            proc.kill()
            raise ValueError("TikTok extraction timed out")

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore").strip()
            if "blocked" in err.lower():
                raise ValueError(
                    "TikTok is blocking server access right now. "
                    "This is a temporary IP-based block — try again in a few hours."
                )
            raise ValueError(f"Could not extract TikTok video: {err[:300]}")

        data = json.loads(stdout)
        title = data.get("title") or "TikTok Video"
        thumbnail = data.get("thumbnail") or ""
        filesize: int | None = data.get("filesize") or data.get("filesize_approx") or None
        duration: float = data.get("duration") or 0

        # yt-dlp's top-level url + http_headers is the best selected format
        video_url = data.get("url") or ""
        cdn_headers: dict = dict(data.get("http_headers") or {})

        # Fallback: scan formats for best video
        if not video_url:
            for fmt in reversed(data.get("formats") or []):
                if fmt.get("vcodec") != "none" and fmt.get("url"):
                    video_url = fmt["url"]
                    cdn_headers = dict(fmt.get("http_headers") or cdn_headers)
                    break

        if not video_url:
            raise ValueError("Could not resolve TikTok video URL")

        # The TikTok CDN URL contains `tk=tt_chain_token` which requires the matching
        # cookie from the WAF challenge. Parse it from the cookie file yt-dlp wrote.
        if "tt_chain_token" in video_url:
            cookies = _parse_netscape_cookies(cookie_file)
            token = cookies.get("tt_chain_token", "")
            if token:
                existing = cdn_headers.get("Cookie", "")
                if existing:
                    cdn_headers["Cookie"] = f"{existing}; tt_chain_token={token}"
                else:
                    cdn_headers["Cookie"] = f"tt_chain_token={token}"

        return MediaInfo(
            title=title,
            thumbnail=thumbnail,
            platform="tiktok",
            formats=[
                Format(id="mp4", label="MP4 Video", ext="mp4",
                       direct_url=video_url, http_headers=cdn_headers, filesize=filesize),
                Format(id="mp3", label="MP3 Audio", ext="mp3",
                       direct_url=video_url, http_headers=cdn_headers, needs_audio_extract=True,
                       filesize=int(duration * 24000) if duration else None),
            ],
        )
