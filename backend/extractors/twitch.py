import random
import re
import urllib.parse

import httpx

from .base import BaseExtractor, Format, MediaInfo
from config import (
    TWITCH_CLIENT_ID as _CLIENT_ID,
    TWITCH_VIDEO_METADATA_HASH as _VIDEO_METADATA_HASH,
    TWITCH_SHARE_CLIP_HASH as _SHARE_CLIP_HASH,
)

_GQL = "https://gql.twitch.tv/gql"
_USHER = "https://usher.ttvnw.net"


class TwitchExtractor(BaseExtractor):
    def match(self, url: str) -> bool:
        return "twitch.tv" in url

    async def extract_info(self, url: str) -> MediaInfo:
        if "/clip/" in url or "clips.twitch.tv" in url:
            return await self._clip_info(url)
        if "/videos/" in url:
            return await self._vod_info(url)
        raise ValueError("Unsupported Twitch URL. Paste a VOD (/videos/...) or clip URL.")

    # ── VOD ────────────────────────────────────────────────────────────────────

    async def _vod_info(self, url: str) -> MediaInfo:
        vod_id = self._parse_vod_id(url)

        meta = await self._video_metadata(vod_id)
        title = meta.get("title") or "Twitch VOD"
        thumbnail = meta.get("previewThumbnailURL") or ""
        length = meta.get("lengthSeconds") or 0
        vod_duration = int(length) if length else 0

        # A signed access token unlocks the usher HLS master playlist.
        token = await self._access_token(vod_id)
        master = await self._fetch_usher(vod_id, token["value"], token["signature"])
        variants = self._parse_master_m3u8(master)
        if not variants:
            raise ValueError("No downloadable qualities found for this VOD")

        formats: list[Format] = []
        for v in variants:
            if v["height"] <= 0:
                continue  # audio-only rendition, used for MP3 below
            label = f"MP4 {v['height']}p" + (f" {int(v['fps'])}fps" if v["fps"] > 30 else "")
            fsize = int(v["bandwidth"] / 8 * vod_duration) if v["bandwidth"] and vod_duration else None
            formats.append(Format(
                id=f"mp4_{v['name'] or v['height']}",
                label=label,
                ext="mp4",
                direct_url=v["url"],
                is_hls=True,
                filesize=fsize,
            ))

        if not formats:
            raise ValueError("No downloadable qualities found for this VOD")

        # Audio-only rendition (last after sort) — same track, far less data to pull.
        audio_url = variants[-1]["url"]
        formats.append(Format(
            id="m4a", label="M4A Audio", ext="m4a",
            direct_url=audio_url, is_hls=True,
        ))
        formats.append(Format(
            id="mp3", label="MP3 Audio", ext="mp3",
            direct_url=audio_url, is_hls=True,
            filesize=int(vod_duration * 24000) if vod_duration else None,
        ))

        return MediaInfo(title=title, thumbnail=thumbnail, platform="twitch_vod",
                         formats=formats, duration=vod_duration or None)

    async def _access_token(self, vod_id: str) -> dict:
        query = (
            "{ videoPlaybackAccessToken("
            f'id: "{vod_id}", '
            'params: { platform: "web", playerBackend: "mediaplayer", playerType: "site" }'
            ") { value signature } }"
        )
        data = await self._gql({"query": query})
        tok = (data.get("data") or {}).get("videoPlaybackAccessToken")
        if not tok:
            raise ValueError("Could not authorize this Twitch VOD (it may be private or deleted)")
        return tok

    async def _video_metadata(self, vod_id: str) -> dict:
        payload = [{
            "operationName": "VideoMetadata",
            "variables": {"channelLogin": "", "videoID": vod_id},
            "extensions": {"persistedQuery": {"version": 1, "sha256Hash": _VIDEO_METADATA_HASH}},
        }]
        data = await self._gql(payload)
        video = (data[0].get("data") or {}).get("video")
        if not video:
            raise ValueError(f"Twitch VOD not found: {vod_id}")
        return video

    async def _fetch_usher(self, vod_id: str, token_value: str, signature: str) -> str:
        params = {
            "allow_source": "true",
            "allow_audio_only": "true",
            "allow_spectre": "true",
            "p": random.randint(1000000, 10000000),
            "platform": "web",
            "player": "twitchweb",
            "supported_codecs": "av1,h265,h264",
            "playlist_include_framerate": "true",
            "sig": signature,
            "token": token_value,
        }
        url = f"{_USHER}/vod/{vod_id}.m3u8?{urllib.parse.urlencode(params)}"
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.text

    def _parse_master_m3u8(self, text: str) -> list[dict]:
        """Parse a Twitch usher master playlist into quality variants."""
        variants: list[dict] = []
        lines = text.splitlines()
        name: str | None = None
        for i, line in enumerate(lines):
            if line.startswith("#EXT-X-MEDIA:"):
                m = re.search(r'NAME="([^"]+)"', line)
                name = m.group(1) if m else None
            elif line.startswith("#EXT-X-STREAM-INF:"):
                res = re.search(r"RESOLUTION=\d+x(\d+)", line)
                bw = re.search(r"BANDWIDTH=(\d+)", line)
                fr = re.search(r"FRAME-RATE=([\d.]+)", line)
                url_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if url_line and not url_line.startswith("#"):
                    variants.append({
                        "name": name,
                        "height": int(res.group(1)) if res else 0,
                        "fps": float(fr.group(1)) if fr else 30.0,
                        "bandwidth": int(bw.group(1)) if bw else 0,
                        "url": url_line,
                    })
                name = None
        variants.sort(key=lambda v: v["height"], reverse=True)
        return variants

    # ── Clip ─────────────────────────────────────────────────────────────────

    async def _clip_info(self, url: str) -> MediaInfo:
        slug = self._parse_clip_slug(url)
        query = [{"operationName": "ShareClipRenderStatus", "variables": {"slug": slug},
                  "extensions": {"persistedQuery": {"version": 1, "sha256Hash": _SHARE_CLIP_HASH}}}]
        data = await self._gql(query)
        clip = data[0]["data"]["clip"]
        if not clip:
            raise ValueError(f"Clip not found: {slug}")

        title = clip.get("title", slug)
        thumbnail = clip.get("thumbnailURL", "")
        clip_duration: float = clip.get("durationSeconds") or 0
        token = clip["playbackAccessToken"]
        sig = token["signature"]
        tok = token["value"]

        assets = clip.get("assets") or []
        qualities = (assets[0].get("videoQualities") or []) if assets else []

        formats: list[Format] = []
        for q in qualities:
            quality = q.get("quality", "")
            fps = q.get("frameRate", "")
            label = f"MP4 {quality}p" + (f" {int(fps)}fps" if fps and float(fps) > 30 else "")
            source_url = f"{q['sourceURL']}?sig={sig}&token={tok}"
            formats.append(Format(
                id=f"mp4_{quality}",
                label=label,
                ext="mp4",
                direct_url=source_url,
            ))

        if not formats:
            raise ValueError("No downloadable qualities found for this clip")

        # Use lowest quality MP4 for audio — same audio track, much less data to download
        audio_src = formats[-1].direct_url
        formats.append(Format(id="m4a", label="M4A Audio", ext="m4a",
                              direct_url=audio_src, needs_audio_extract=True))
        formats.append(Format(id="mp3", label="MP3 Audio", ext="mp3",
                               direct_url=audio_src, needs_audio_extract=True,
                               filesize=int(clip_duration * 24000) if clip_duration else None))

        return MediaInfo(title=title, thumbnail=thumbnail, platform="twitch_clip", formats=formats)

    async def _gql(self, payload):
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                _GQL,
                json=payload,
                headers={"Client-ID": _CLIENT_ID, "Content-Type": "application/json"},
            )
            r.raise_for_status()
            return r.json()

    def _parse_vod_id(self, url: str) -> str:
        match = re.search(r"/videos/(\d+)", url)
        if not match:
            raise ValueError("Could not parse Twitch VOD id")
        return match.group(1)

    def _parse_clip_slug(self, url: str) -> str:
        match = re.search(r"/clip/([^/?]+)", url) or re.search(r"clips\.twitch\.tv/([^/?]+)", url)
        if not match:
            raise ValueError("Could not parse Twitch clip slug")
        return match.group(1)
