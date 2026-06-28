import time

from extractors.base import BaseExtractor, MediaInfo
from extractors.youtube import YouTubeExtractor
from extractors.instagram import InstagramExtractor
from extractors.tiktok import TikTokExtractor
from extractors.twitch import TwitchExtractor

_EXTRACTORS: list[BaseExtractor] = [
    YouTubeExtractor(),
    InstagramExtractor(),
    TikTokExtractor(),
    TwitchExtractor(),
]

# Cache MediaInfo (with CDN URLs) so /api/download reuses the same URL set as /api/info.
# YouTube invalidates / rate-limits the second player API call made with the same visitor data.
_CACHE: dict[str, tuple[float, MediaInfo]] = {}
_TTL = 300  # 5 minutes — CDN URLs typically expire in 6h but refresh early to be safe


def get_extractor(url: str) -> BaseExtractor:
    for extractor in _EXTRACTORS:
        if extractor.match(url):
            return extractor
    raise ValueError(f"No extractor found for URL: {url}")


async def get_info(url: str) -> MediaInfo:
    now = time.monotonic()
    entry = _CACHE.get(url)
    if entry and now - entry[0] < _TTL:
        return entry[1]
    info = await get_extractor(url).extract_info(url)
    _CACHE[url] = (now, info)
    return info
