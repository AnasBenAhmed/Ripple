import json
import re

import httpx

from .base import BaseExtractor, Format, MediaInfo

from config import INSTAGRAM_APP_ID as _APP_ID, INSTAGRAM_DOC_ID as _DOC_ID

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# fbcdn serves these without auth; Referer keeps it happy on some edges.
_IG_HEADERS = {"Referer": "https://www.instagram.com/"}

# csrftoken seeded once from the homepage and reused for the session.
_CSRF_TOKEN: str = ""


class InstagramExtractor(BaseExtractor):
    def match(self, url: str) -> bool:
        return "instagram.com" in url

    async def extract_info(self, url: str) -> MediaInfo:
        shortcode = self._parse_shortcode(url)
        media = await self._fetch_media(shortcode)
        return self._build_media_info(url, media)

    def _parse_shortcode(self, url: str) -> str:
        m = re.search(r"/(?:p|tv|reels?)/([A-Za-z0-9_-]+)", url)
        if not m:
            raise ValueError("Could not extract Instagram post ID from URL")
        return m.group(1)

    async def _get_csrf(self, client: httpx.AsyncClient) -> str:
        """Hit the homepage once to obtain a csrftoken cookie. Cached per process."""
        global _CSRF_TOKEN
        if _CSRF_TOKEN:
            return _CSRF_TOKEN
        await client.get("https://www.instagram.com/", headers={"User-Agent": _UA})
        _CSRF_TOKEN = client.cookies.get("csrftoken", "")
        return _CSRF_TOKEN

    async def _fetch_media(self, shortcode: str) -> dict:
        global _CSRF_TOKEN
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            csrf = await self._get_csrf(client)
            headers = {
                "User-Agent": _UA,
                "X-IG-App-ID": _APP_ID,
                "X-CSRFToken": csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://www.instagram.com/p/{shortcode}/",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            data = {"doc_id": _DOC_ID, "variables": json.dumps({"shortcode": shortcode})}
            r = await client.post("https://www.instagram.com/graphql/query/",
                                  data=data, headers=headers)

            # A stale csrftoken can make IG reject the call — reseed once and retry.
            if r.status_code in (401, 403) or '"data":null' in r.text:
                _CSRF_TOKEN = ""
                csrf = await self._get_csrf(client)
                headers["X-CSRFToken"] = csrf
                r = await client.post("https://www.instagram.com/graphql/query/",
                                      data=data, headers=headers)

        try:
            payload = r.json()
        except json.JSONDecodeError:
            raise ValueError("Instagram returned an unexpected response")

        media = (payload.get("data") or {}).get("xdt_shortcode_media")
        if not media:
            raise ValueError(
                "This Instagram post is private or unavailable. "
                "Public posts and reels download without login."
            )
        return media

    def _caption_title(self, media: dict) -> str:
        edges = media.get("edge_media_to_caption", {}).get("edges", [])
        if edges:
            text = edges[0].get("node", {}).get("text", "").strip()
            if text:
                return text[:80]
        owner = (media.get("owner") or {}).get("username")
        return f"@{owner}" if owner else "Instagram Post"

    def _video_formats(self, media: dict, suffix: str = "") -> list[Format]:
        """Build MP4 + MP3 formats for a single video node."""
        video_url = media.get("video_url")
        if not video_url:
            return []
        dur = media.get("video_duration") or 0
        thumb = media.get("display_url") or media.get("thumbnail_src") or ""
        n = suffix or ""
        sfx = (" " + n.lstrip("_")) if n else ""
        return [
            Format(
                id=f"mp4{n}", label=f"MP4 Video{sfx}",
                ext="mp4", direct_url=video_url, http_headers=_IG_HEADERS, thumbnail=thumb,
            ),
            Format(
                id=f"m4a{n}", label=f"M4A Audio{sfx}",
                ext="m4a", direct_url=video_url, http_headers=_IG_HEADERS,
                needs_audio_extract=True, thumbnail=thumb,
            ),
            Format(
                id=f"mp3{n}", label=f"MP3 Audio{sfx}",
                ext="mp3", direct_url=video_url, http_headers=_IG_HEADERS,
                needs_audio_extract=True, thumbnail=thumb,
                filesize=int(dur * 24000) if dur else None,
            ),
        ]

    def _image_format(self, media: dict, suffix: str = "") -> list[Format]:
        img = media.get("display_url") or media.get("thumbnail_src")
        if not img:
            return []
        n = suffix or ""
        return [Format(
            id=f"image{n or '_1'}", label=f"Image{(' ' + n.lstrip('_')) if n else ' 1'}",
            ext="jpg", direct_url=img, http_headers=_IG_HEADERS, thumbnail=img,
        )]

    def _build_media_info(self, url: str, media: dict) -> MediaInfo:
        title = self._caption_title(media)
        thumbnail = media.get("display_url") or media.get("thumbnail_src") or ""
        duration = int(media.get("video_duration") or 0)
        is_reel = bool(re.search(r"/reels?/", url, re.IGNORECASE))

        formats: list[Format] = []
        children = media.get("edge_sidecar_to_children", {}).get("edges", [])

        if children:
            # Carousel post — one set of formats per child.
            for i, edge in enumerate(children, 1):
                node = edge.get("node", {})
                if node.get("is_video"):
                    formats += self._video_formats(node, suffix=f"_{i}")
                else:
                    formats += self._image_format(node, suffix=f"_{i}")
            platform = "instagram_post"
        elif media.get("is_video"):
            formats += self._video_formats(media)
            platform = "instagram" if is_reel else "instagram_post"
        else:
            formats += self._image_format(media)
            platform = "instagram_post"

        if not formats:
            raise ValueError("No downloadable content found in this Instagram post")

        return MediaInfo(
            title=title, thumbnail=thumbnail, platform=platform,
            formats=formats, duration=duration or None,
        )
