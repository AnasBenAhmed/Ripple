import asyncio
import json
import re

import httpx

from .base import BaseExtractor, Format, MediaInfo

# Twitch web player client ID (from yt-dlp)
_CLIENT_ID = "ue6666qo983tsx6so1t0vnawi233wa"

_GQL = "https://gql.twitch.tv/gql"


class TwitchExtractor(BaseExtractor):
    def match(self, url: str) -> bool:
        return "twitch.tv" in url

    async def extract_info(self, url: str) -> MediaInfo:
        if "/clip/" in url or "clips.twitch.tv" in url:
            return await self._clip_info(url)
        if "/videos/" in url:
            return await self._vod_info(url)
        raise ValueError("Unsupported Twitch URL. Paste a VOD (/videos/...) or clip URL.")

    # ── VOD (via yt-dlp — usher.twitchapps.com doesn't resolve universally) ──

    async def _vod_info(self, url: str) -> MediaInfo:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp", "--dump-json", "--no-download", "--quiet", "--no-warnings",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            raise ValueError(f"Could not extract Twitch VOD: {stderr.decode(errors='replace')[:200]}")

        data = json.loads(stdout)
        title = data.get("title") or "Twitch VOD"
        thumbnail = data.get("thumbnail", "")
        duration = data.get("duration")
        vod_duration: int = int(duration) if duration else 0

        raw = [
            f for f in data.get("formats", [])
            if f.get("protocol") in ("m3u8", "m3u8_native")
            and f.get("vcodec", "none") != "none"
            and f.get("acodec", "none") != "none"
        ]
        raw.sort(key=lambda f: f.get("height") or 0, reverse=True)

        formats: list[Format] = []
        seen: set[str] = set()
        for f in raw:
            fid = f["format_id"]
            if fid in seen:
                continue
            seen.add(fid)
            height = f.get("height") or 0
            fps = f.get("fps") or 30
            label = f"MP4 {height}p" + (f" {int(fps)}fps" if fps > 30 else "")
            tbr = f.get("tbr") or 0
            fsize: int | None = int(tbr * 1000 / 8 * vod_duration) if tbr and vod_duration else None
            formats.append(Format(
                id=f"mp4_{fid}",
                label=label,
                ext="mp4",
                direct_url=f["url"],
                is_hls=True,
                filesize=fsize,
            ))

        if not formats:
            raise ValueError("No downloadable qualities found for this VOD")

        # Use the lowest quality HLS stream for audio — same audio track, ~26x less data to download
        formats.append(Format(
            id="mp3", label="MP3 Audio", ext="mp3",
            direct_url=formats[-1].direct_url, is_hls=True,
            filesize=int(vod_duration * 24000) if vod_duration else None,
        ))

        return MediaInfo(title=title, thumbnail=thumbnail, platform="twitch_vod", formats=formats, duration=duration)

    # ── Clip ─────────────────────────────────────────────────────────────────

    async def _clip_info(self, url: str) -> MediaInfo:
        slug = self._parse_clip_slug(url)
        query = [{"operationName": "ShareClipRenderStatus", "variables": {"slug": slug},
                  "extensions": {"persistedQuery": {
                      "version": 1,
                      "sha256Hash": "0a02bb974443b576f5579aab0fef1d4b7f44e58a8a256f0c5adfead0db70640f",
                  }}}]
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

        # Qualities live in assets[0].videoQualities (yt-dlp's ShareClipRenderStatus structure)
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
        formats.append(Format(id="mp3", label="MP3 Audio", ext="mp3",
                               direct_url=formats[-1].direct_url, needs_audio_extract=True,
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

    def _parse_clip_slug(self, url: str) -> str:
        match = re.search(r"/clip/([^/?]+)", url) or re.search(r"clips\.twitch\.tv/([^/?]+)", url)
        if not match:
            raise ValueError("Could not parse Twitch clip slug")
        return match.group(1)
