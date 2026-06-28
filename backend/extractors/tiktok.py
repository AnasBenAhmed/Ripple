import asyncio
import json
import re

import httpx

from .base import BaseExtractor, Format, MediaInfo

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_BROWSER_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

# The video page embeds all media metadata in this hydration blob.
_UNIVERSAL_DATA_RE = re.compile(
    r'<script[^>]+\bid="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# TikTok only serves the hydration blob to "warmed" sessions that carry the
# cookies its homepage hands out over a few requests.


class TikTokExtractor(BaseExtractor):
    def match(self, url: str) -> bool:
        return "tiktok.com" in url

    async def extract_info(self, url: str) -> MediaInfo:
        item, page_url = await self._fetch_item(url)

        video = item.get("video") or {}
        title = (item.get("desc") or "TikTok Video").strip()[:80] or "TikTok Video"
        thumbnail = self._first_url(video, ("cover", "originCover", "dynamicCover")) or ""
        duration = int(video.get("duration") or 0)

        # The CDN only needs Referer + UA; sending the session Cookie triggers a 403.
        cdn_headers = {"Referer": page_url, "User-Agent": _UA}

        video_url, filesize = self._best_video(video)

        formats: list[Format] = []
        if video_url:
            formats.append(Format(
                id="mp4", label="MP4 Video", ext="mp4",
                direct_url=video_url, http_headers=cdn_headers, filesize=filesize,
            ))
            formats.append(Format(
                id="mp3", label="MP3 Audio", ext="mp3",
                direct_url=video_url, http_headers=cdn_headers, needs_audio_extract=True,
                filesize=int(duration * 24000) if duration else None,
            ))
        else:
            # Photo slideshow — only the music track is downloadable as audio.
            music_url = (item.get("music") or {}).get("playUrl")
            if music_url:
                formats.append(Format(
                    id="mp3", label="MP3 Audio", ext="mp3",
                    direct_url=music_url, http_headers=cdn_headers, needs_audio_extract=True,
                ))

        if not formats:
            raise ValueError("Could not resolve a downloadable TikTok video URL")

        return MediaInfo(
            title=title, thumbnail=thumbnail, platform="tiktok",
            formats=formats, duration=duration or None,
        )

    async def _warm(self, client: httpx.AsyncClient) -> None:
        """Hit the homepage a few times so TikTok hands out the cookies that unlock video data."""
        for _ in range(4):
            try:
                await client.get("https://www.tiktok.com/")
            except httpx.HTTPError:
                return
            if client.cookies.get("msToken"):
                return
            await asyncio.sleep(0.5)

    async def _fetch_item(self, url: str) -> tuple[dict, str]:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True,
                                     headers=_BROWSER_HEADERS) as client:
            await self._warm(client)

            r = await client.get(url)
            r.raise_for_status()

            # A challenged/cold session returns a page without the hydration blob.
            # Re-warm once and retry before giving up.
            if "__UNIVERSAL_DATA_FOR_REHYDRATION__" not in r.text:
                await self._warm(client)
                r = await client.get(url)
                r.raise_for_status()

            page_url = str(r.url)

        m = _UNIVERSAL_DATA_RE.search(r.text)
        if not m:
            raise ValueError(
                "TikTok did not return video data. The link may be private, "
                "region-locked, or removed."
            )

        try:
            scope = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
        except json.JSONDecodeError:
            raise ValueError("Could not parse TikTok video data")

        detail = scope.get("webapp.video-detail", {})
        status = detail.get("statusCode", 0)
        if status and status != 0:
            raise ValueError(
                "TikTok video is unavailable (it may be private, deleted, or age-restricted)."
            )

        item = (detail.get("itemInfo") or {}).get("itemStruct")
        if not item:
            raise ValueError("No media found for this TikTok link")
        return item, page_url

    def _best_video(self, video: dict) -> tuple[str, int | None]:
        """Pick the highest-quality watermark-free stream from bitrateInfo / playAddr."""
        best_url = ""
        best_size: int | None = None
        best_bitrate = -1
        for bi in video.get("bitrateInfo") or []:
            play = bi.get("PlayAddr") or {}
            urls = [u for u in (play.get("UrlList") or []) if u]
            if not urls:
                continue
            br = bi.get("Bitrate") or 0
            if br > best_bitrate:
                best_bitrate = br
                best_url = urls[-1]  # last entry is the most broadly reachable CDN
                best_size = play.get("DataSize")

        if not best_url:
            best_url = video.get("playAddr") or video.get("downloadAddr") or ""
        return best_url, best_size

    def _first_url(self, obj: dict, keys: tuple[str, ...]) -> str:
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        return ""
