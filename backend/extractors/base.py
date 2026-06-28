from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Format:
    id: str
    label: str
    ext: str
    video_url: str | None = None
    audio_url: str | None = None
    direct_url: str | None = None
    needs_merge: bool = False
    needs_audio_extract: bool = False  # extract audio from a combined video URL via ffmpeg
    is_hls: bool = False              # URL is an M3U8 playlist — use ffmpeg to download
    http_headers: dict | None = None  # extra headers required by the CDN (e.g. Referer)
    thumbnail: str | None = None      # per-format preview URL (used for image carousel items)
    filesize: int | None = None       # bytes, used for Content-Length; None = unknown


@dataclass
class MediaInfo:
    title: str
    thumbnail: str
    platform: str
    formats: list[Format]
    duration: int | None = None  # seconds


class BaseExtractor(ABC):
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    @abstractmethod
    async def extract_info(self, url: str) -> MediaInfo:
        """Return media metadata and available formats."""
        ...

    @abstractmethod
    def match(self, url: str) -> bool:
        """Return True if this extractor handles the given URL."""
        ...
