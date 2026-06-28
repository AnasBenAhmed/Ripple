import asyncio
import json
import os
import re

from .base import BaseExtractor, Format, MediaInfo

_IG_HEADERS = {"Referer": "https://www.instagram.com/"}

# Drop a Netscape cookies.txt file here (exported from Chrome via "Get cookies.txt LOCALLY")
_COOKIES_FILE = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "cookies", "instagram.txt")
)


class InstagramExtractor(BaseExtractor):
    def match(self, url: str) -> bool:
        return "instagram.com" in url

    async def extract_info(self, url: str) -> MediaInfo:
        m = re.search(r"/(?:p|tv|reels?)/([A-Za-z0-9_-]+)", url)
        if not m:
            raise ValueError("Could not extract Instagram post ID from URL")
        return await self._from_ytdlp(url)

    async def _from_ytdlp(self, url: str) -> MediaInfo:
        cmd = ["yt-dlp", "--dump-json", "--no-download", "--quiet", "--no-warnings"]

        if os.path.exists(_COOKIES_FILE):
            cmd += ["--cookies", _COOKIES_FILE]

        cmd.append(url)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            needs_login = any(k in err.lower() for k in ("login", "authentication", "cookies", "empty media", "private"))
            if needs_login:
                raise ValueError(
                    "Instagram requires login for this content. "
                    "Fix: install the 'Get cookies.txt LOCALLY' Chrome extension, "
                    "export instagram.com cookies, and save the file to: "
                    "ripple/backend/cookies/instagram.txt"
                )
            raise ValueError(
                f"Could not extract this Instagram post. "
                f"{err[:160].strip() if err else 'Unknown error'}"
            )

        raw = stdout.decode(errors="replace").strip()
        if not raw:
            raise ValueError(
                "Instagram returned no media data. "
                "The post may require login — add your cookies to "
                "ripple/backend/cookies/instagram.txt"
            )

        # yt-dlp outputs one JSON object per line for playlists
        json_lines = [l.strip() for l in raw.splitlines() if l.strip().startswith("{")]
        if not json_lines:
            raise ValueError("No media data found for this Instagram post")

        data = json.loads(json_lines[0])

        title = (data.get("title") or data.get("description") or "Instagram Post")[:80]
        thumbnail = data.get("thumbnail") or ""
        duration: float = data.get("duration") or 0
        entries = data.get("entries") or []
        is_reel = bool(re.search(r"/reels?/", url, re.IGNORECASE))

        formats: list[Format] = []

        if entries:
            # Carousel post
            for i, entry in enumerate(entries, 1):
                vid_url = entry.get("url") or ""
                ext = entry.get("ext", "mp4")
                thumb = entry.get("thumbnail") or ""
                ent_dur: float = entry.get("duration") or 0
                fs = entry.get("filesize") or entry.get("filesize_approx") or None
                if vid_url and ext in ("mp4", "m4v", "mov", "webm"):
                    formats.append(Format(
                        id=f"video_{i}", label=f"Video {i}", ext="mp4",
                        direct_url=vid_url, http_headers=_IG_HEADERS,
                        thumbnail=thumb, filesize=fs,
                    ))
                    formats.append(Format(
                        id=f"audio_{i}", label=f"Audio {i}", ext="mp3",
                        direct_url=vid_url, http_headers=_IG_HEADERS,
                        needs_audio_extract=True,
                        filesize=int(ent_dur * 24000) if ent_dur else None,
                        thumbnail=thumb,
                    ))
                elif vid_url:
                    formats.append(Format(
                        id=f"image_{i}", label=f"Image {i}", ext="jpg",
                        direct_url=vid_url, http_headers=_IG_HEADERS, thumbnail=thumb,
                    ))
            platform = "instagram_post"
        else:
            # Single video or image
            vid_url = data.get("url") or ""
            ext = data.get("ext", "mp4")
            filesize = data.get("filesize") or data.get("filesize_approx") or None
            if vid_url and ext in ("mp4", "m4v", "mov", "webm"):
                formats.append(Format(
                    id="mp4", label="MP4 Video", ext="mp4",
                    direct_url=vid_url, http_headers=_IG_HEADERS, filesize=filesize,
                ))
                formats.append(Format(
                    id="mp3", label="MP3 Audio", ext="mp3",
                    direct_url=vid_url, http_headers=_IG_HEADERS,
                    needs_audio_extract=True,
                    filesize=int(duration * 24000) if duration else None,
                ))
            elif thumbnail:
                formats.append(Format(
                    id="image_1", label="Image 1", ext="jpg",
                    direct_url=thumbnail, http_headers=_IG_HEADERS,
                ))
            platform = "instagram" if is_reel else "instagram_post"

        if not formats:
            raise ValueError("No downloadable content found in this Instagram post")

        return MediaInfo(
            title=title, thumbnail=thumbnail, platform=platform,
            formats=formats,
            duration=int(duration) if duration else None,
        )
