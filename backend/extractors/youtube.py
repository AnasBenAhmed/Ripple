import json
import re

import httpx

from .base import BaseExtractor, Format, MediaInfo
from config import (
    YOUTUBE_CLIENT_NAME, YOUTUBE_CLIENT_NAME_ID,
    YOUTUBE_CLIENT_VERSION, YOUTUBE_USER_AGENT,
)

_VISITOR_DATA_CACHE: str = ""


def _parse_clen(url: str) -> int | None:
    m = re.search(r'[?&]clen=(\d+)', url)
    return int(m.group(1)) if m else None


def _height_label(height: int) -> str:
    for label in ("1080", "720", "480", "360"):
        if height >= int(label):
            return f"{label}p"
    return f"{height}p"


class YouTubeExtractor(BaseExtractor):
    def match(self, url: str) -> bool:
        return bool(re.search(r"(youtube\.com/(?:watch|shorts/|live/)|youtu\.be/)", url))

    async def extract_info(self, url: str) -> MediaInfo:
        video_id = self._parse_id(url)
        visitor_data = await self._get_visitor_data()
        player = await self._fetch_player(video_id, visitor_data)

        title = player["videoDetails"]["title"]
        thumbnail = player["videoDetails"]["thumbnail"]["thumbnails"][-1]["url"]
        adaptive = player.get("streamingData", {}).get("adaptiveFormats", [])
        formats = self._build_formats(adaptive)

        platform = "youtube_short" if "/shorts/" in url else "youtube"
        return MediaInfo(title=title, thumbnail=thumbnail, platform=platform, formats=formats)

    def _parse_id(self, url: str) -> str:
        match = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([A-Za-z0-9_-]{11})", url)
        if not match:
            raise ValueError("Could not parse YouTube video ID")
        return match.group(1)

    async def _get_visitor_data(self) -> str:
        global _VISITOR_DATA_CACHE
        if _VISITOR_DATA_CACHE:
            return _VISITOR_DATA_CACHE

        async with httpx.AsyncClient(timeout=15, headers={
            "User-Agent": self.HEADERS["User-Agent"],
            "Accept-Language": "en-US,en;q=0.9",
        }) as client:
            r = await client.get("https://www.youtube.com/")

        # Extract visitorData from ytcfg.set({...})
        visitor_data = ""
        m = re.search(r'ytcfg\.set\s*\(\s*(\{.+?\})\s*\)\s*;', r.text, re.DOTALL)
        if m:
            try:
                cfg = json.loads(m.group(1))
                visitor_data = (
                    cfg.get("VISITOR_DATA")
                    or cfg.get("INNERTUBE_CONTEXT", {}).get("client", {}).get("visitorData", "")
                )
            except (json.JSONDecodeError, AttributeError):
                pass

        if not visitor_data:
            m2 = re.search(r'"visitorData":"([^"]+)"', r.text)
            if m2:
                visitor_data = m2.group(1)

        _VISITOR_DATA_CACHE = visitor_data
        return visitor_data

    async def _fetch_player(self, video_id: str, visitor_data: str) -> dict:
        # ANDROID_VR (Oculus Quest 3) InnerTube client — returns unthrottled
        # adaptive formats without a poToken when a valid visitorData is supplied.
        payload = {
            "videoId": video_id,
            "context": {
                "client": {
                    "clientName": YOUTUBE_CLIENT_NAME,
                    "clientVersion": YOUTUBE_CLIENT_VERSION,
                    "deviceMake": "Oculus",
                    "deviceModel": "Quest 3",
                    "androidSdkVersion": 32,
                    "userAgent": YOUTUBE_USER_AGENT,
                    "osName": "Android",
                    "osVersion": "12L",
                    "hl": "en",
                    "gl": "US",
                    "visitorData": visitor_data,
                }
            },
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": YOUTUBE_USER_AGENT,
            "X-YouTube-Client-Name": YOUTUBE_CLIENT_NAME_ID,
            "X-YouTube-Client-Version": YOUTUBE_CLIENT_VERSION,
            "X-Goog-Visitor-Id": visitor_data,
            "Accept-Language": "en-US,en;q=0.9",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                "https://www.youtube.com/youtubei/v1/player",
                json=payload,
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()

        status = data.get("playabilityStatus", {})
        if status.get("status") not in ("OK", None):
            reason = status.get("reason", "Video unavailable")
            raise ValueError(reason)
        return data

    def _build_formats(self, adaptive: list[dict]) -> list[Format]:
        video_streams: dict[str, dict] = {}
        best_audio: dict | None = None

        for s in adaptive:
            mime = s.get("mimeType", "")
            if "video/mp4" in mime and "avc1" in mime:
                height = s.get("height", 0)
                label = _height_label(height)
                if label not in video_streams or s.get("bitrate", 0) > video_streams[label].get("bitrate", 0):
                    video_streams[label] = s
            elif "audio/mp4" in mime:
                if best_audio is None or s.get("bitrate", 0) > best_audio.get("bitrate", 0):
                    best_audio = s

        audio_clen = _parse_clen(best_audio["url"]) if best_audio else None

        formats: list[Format] = []
        for label in ("1080p", "720p", "480p", "360p"):
            if label in video_streams and best_audio:
                vclen = _parse_clen(video_streams[label]["url"])
                fs = (vclen + audio_clen) if vclen and audio_clen else None
                formats.append(Format(
                    id=f"mp4_{label}",
                    label=f"MP4 {label}",
                    ext="mp4",
                    video_url=video_streams[label]["url"],
                    audio_url=best_audio["url"],
                    needs_merge=True,
                    filesize=fs,
                ))

        if best_audio:
            # M4A = the AAC stream copied straight through (fast). MP3 = real
            # transcode (still fast — the audio is pulled via the CDN proxy).
            formats.append(Format(
                id="m4a",
                label="M4A Audio",
                ext="m4a",
                audio_url=best_audio["url"],
                filesize=audio_clen,
            ))
            formats.append(Format(
                id="mp3",
                label="MP3 Audio",
                ext="mp3",
                audio_url=best_audio["url"],
                needs_audio_extract=True,
                filesize=audio_clen,
            ))

        return formats
