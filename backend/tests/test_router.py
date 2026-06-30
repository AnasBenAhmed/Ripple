"""URL → platform detection tests.

Covers each extractor's `match()` (does it recognise its own URLs and reject
the others?) and the router's `get_extractor()` dispatch. All pure logic — no
network calls are made.
"""
import pytest

from services.router import get_extractor
from extractors.youtube import YouTubeExtractor
from extractors.instagram import InstagramExtractor
from extractors.tiktok import TikTokExtractor
from extractors.twitch import TwitchExtractor

YOUTUBE_URLS = [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/abc123",
    "https://www.youtube.com/live/xyz789",
]
INSTAGRAM_URLS = [
    "https://www.instagram.com/reel/DZ9w3D3txED/",
    "https://instagram.com/p/Cabc123/",
]
TIKTOK_URLS = [
    "https://www.tiktok.com/@user/video/7300000000000000000",
    "https://vm.tiktok.com/ZMabc123/",
]
TWITCH_URLS = [
    "https://www.twitch.tv/videos/123456789",
    "https://clips.twitch.tv/SomeClipSlug",
    "https://twitch.tv/somestreamer",
]


class TestMatch:
    @pytest.mark.parametrize("url", YOUTUBE_URLS)
    def test_youtube_matches_its_own_urls(self, url):
        assert YouTubeExtractor().match(url) is True

    @pytest.mark.parametrize("url", INSTAGRAM_URLS)
    def test_instagram_matches_its_own_urls(self, url):
        assert InstagramExtractor().match(url) is True

    @pytest.mark.parametrize("url", TIKTOK_URLS)
    def test_tiktok_matches_its_own_urls(self, url):
        assert TikTokExtractor().match(url) is True

    @pytest.mark.parametrize("url", TWITCH_URLS)
    def test_twitch_matches_its_own_urls(self, url):
        assert TwitchExtractor().match(url) is True

    def test_youtube_ignores_other_platforms(self):
        for url in INSTAGRAM_URLS + TIKTOK_URLS + TWITCH_URLS:
            assert YouTubeExtractor().match(url) is False

    def test_youtube_channel_page_is_not_a_video(self):
        # Only /watch, /shorts/, /live/, and youtu.be are real media URLs.
        assert YouTubeExtractor().match("https://www.youtube.com/@channel") is False

    def test_extractors_do_not_cross_match(self):
        assert InstagramExtractor().match(TIKTOK_URLS[0]) is False
        assert TikTokExtractor().match(TWITCH_URLS[0]) is False
        assert TwitchExtractor().match(YOUTUBE_URLS[0]) is False


class TestRouter:
    @pytest.mark.parametrize("url", YOUTUBE_URLS)
    def test_routes_youtube(self, url):
        assert isinstance(get_extractor(url), YouTubeExtractor)

    @pytest.mark.parametrize("url", INSTAGRAM_URLS)
    def test_routes_instagram(self, url):
        assert isinstance(get_extractor(url), InstagramExtractor)

    @pytest.mark.parametrize("url", TIKTOK_URLS)
    def test_routes_tiktok(self, url):
        assert isinstance(get_extractor(url), TikTokExtractor)

    @pytest.mark.parametrize("url", TWITCH_URLS)
    def test_routes_twitch(self, url):
        assert isinstance(get_extractor(url), TwitchExtractor)

    def test_unsupported_url_raises(self):
        with pytest.raises(ValueError):
            get_extractor("https://vimeo.com/123456789")
