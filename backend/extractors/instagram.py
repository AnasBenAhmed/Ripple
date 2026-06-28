import functools
import json
import re
import string

import httpx

from .base import BaseExtractor, Format, MediaInfo

_APP_ID = "936619743392459"
_ALPHABET = string.ascii_uppercase + string.ascii_lowercase + string.digits + "-_"


def _shortcode_to_pk(shortcode: str) -> int:
    return functools.reduce(lambda acc, x: acc * 64 + _ALPHABET.index(x), shortcode, 0)


class InstagramExtractor(BaseExtractor):
    def match(self, url: str) -> bool:
        return "instagram.com" in url

    async def extract_info(self, url: str) -> MediaInfo:
        m = re.search(r"/(?:p|tv|reels?)/([A-Za-z0-9_-]+)", url)
        if not m:
            raise ValueError("Could not extract Instagram post ID from URL")
        shortcode = m.group(1)
        pk = _shortcode_to_pk(shortcode)

        api_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "X-IG-App-ID": _APP_ID,
            "X-ASBD-ID": "198387",
            "X-IG-WWW-Claim": "0",
            "Origin": "https://www.instagram.com",
            "Referer": url,
            "Accept": "*/*",
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            # Step 1: Hit Instagram's ruling API to set up session cookies (including csrftoken)
            await client.get(
                f"https://i.instagram.com/api/v1/web/get_ruling_for_content/"
                f"?content_type=MEDIA&target_id={pk}",
                headers=api_headers,
            )
            csrf = client.cookies.get("csrftoken", "")

            # Step 2: GraphQL query (yt-dlp's primary method)
            variables = json.dumps({
                "shortcode": shortcode,
                "child_comment_count": 3,
                "fetch_comment_count": 40,
                "parent_comment_count": 24,
                "has_threaded_comments": True,
            }, separators=(",", ":"))

            gql_r = await client.get(
                "https://www.instagram.com/graphql/query/",
                headers={**api_headers, "X-CSRFToken": csrf, "X-Requested-With": "XMLHttpRequest"},
                params={"doc_id": "8845758582119845", "variables": variables},
            )
            if gql_r.status_code == 200:
                try:
                    gql_data = gql_r.json()
                    media = gql_data.get("data", {}).get("xdt_shortcode_media") or {}
                    if media:
                        return _from_graphql(media)
                except (json.JSONDecodeError, AttributeError):
                    pass

            # Step 3: Embed page fallback (yt-dlp's fallback for non-logged-in)
            embed_r = await client.get(
                f"https://www.instagram.com/p/{shortcode}/embed/",
                headers={**api_headers, "Accept": "text/html"},
            )
            text = embed_r.text

            # Try __additionalDataLoaded (product items)
            am = re.search(r'window\.__additionalDataLoaded\s*\([^,]+,\s*(\{.+?\})\s*\)\s*;', text, re.DOTALL)
            if am:
                try:
                    add = json.loads(am.group(1))
                    item = (add.get("items") or [None])[0]
                    if item:
                        return _from_product(item)
                    sm = (add.get("graphql") or {}).get("shortcode_media") or add.get("shortcode_media")
                    if sm:
                        return _from_graphql(sm)
                except (json.JSONDecodeError, AttributeError):
                    pass

            # Try _sharedData
            sdm = re.search(r'window\._sharedData\s*=\s*(\{.+?\})\s*;', text, re.DOTALL)
            if sdm:
                try:
                    sd = json.loads(sdm.group(1))
                    sm = (
                        (sd.get("entry_data") or {}).get("PostPage", [{}])[0]
                        .get("graphql", {})
                        .get("shortcode_media")
                    )
                    if sm:
                        return _from_graphql(sm)
                except (json.JSONDecodeError, AttributeError, IndexError):
                    pass

        raise ValueError("Could not extract this Instagram post. It may be private or require login.")


_IG_HEADERS = {"Referer": "https://www.instagram.com/"}


def _caption_title(media: dict, fallback: str = "Instagram Post") -> str:
    caption_edges = (media.get("edge_media_to_caption") or {}).get("edges") or []
    caption = (caption_edges[0].get("node", {}).get("text") if caption_edges else None) or ""
    return (caption[:80] if caption else None) or media.get("title") or fallback


def _from_graphql(media: dict) -> MediaInfo:
    title = _caption_title(media)
    thumbnail = media.get("display_url") or media.get("thumbnail_src") or ""
    video_url = media.get("video_url")
    nodes = (media.get("edge_sidecar_to_children") or {}).get("edges") or []

    if video_url:
        return _make_video_info(video_url, title, thumbnail, duration=media.get("video_duration") or 0)

    if nodes:
        return _make_carousel_info(nodes, title, thumbnail)

    # Single image post
    if thumbnail:
        return MediaInfo(title=title, thumbnail=thumbnail, platform="instagram_post", formats=[
            Format(id="image_1", label="Image 1", ext="jpg",
                   direct_url=thumbnail, http_headers=_IG_HEADERS, thumbnail=thumbnail),
        ])

    raise ValueError("Could not extract media from this Instagram post.")


def _from_product(item: dict) -> MediaInfo:
    cap = item.get("caption") or {}
    title = ((cap.get("text") if isinstance(cap, dict) else str(cap)) or "")[:80] or "Instagram Post"
    thumb_candidates = (item.get("image_versions2") or {}).get("candidates") or []
    thumbnail = (thumb_candidates[0].get("url") if thumb_candidates else "") or ""

    carousel_media = item.get("carousel_media") or []
    if carousel_media:
        return _make_product_carousel(carousel_media, title, thumbnail)

    versions = item.get("video_versions") or []
    video_url = (versions[0].get("url") if versions else None) or item.get("video_url") or ""
    if video_url:
        return _make_video_info(video_url, title, thumbnail, duration=item.get("video_duration") or 0)

    if thumbnail:
        return MediaInfo(title=title, thumbnail=thumbnail, platform="instagram_post", formats=[
            Format(id="image_1", label="Image 1", ext="jpg",
                   direct_url=thumbnail, http_headers=_IG_HEADERS, thumbnail=thumbnail),
        ])

    raise ValueError("Could not extract media from this Instagram post.")


def _make_video_info(video_url: str, title: str, thumbnail: str, duration: float = 0) -> MediaInfo:
    return MediaInfo(title=title, thumbnail=thumbnail, platform="instagram", formats=[
        Format(id="mp4", label="MP4 Video", ext="mp4", direct_url=video_url, http_headers=_IG_HEADERS),
        Format(id="mp3", label="MP3 Audio", ext="mp3", direct_url=video_url,
               http_headers=_IG_HEADERS, needs_audio_extract=True,
               filesize=int(duration * 24000) if duration else None),
    ])


def _make_carousel_info(nodes: list, title: str, thumbnail: str) -> MediaInfo:
    formats: list[Format] = []
    for i, edge in enumerate(nodes, 1):
        node = edge.get("node", {})
        video_url = node.get("video_url")
        display_url = node.get("display_url") or ""
        if video_url:
            node_dur = node.get("video_duration") or 0
            formats.append(Format(id=f"video_{i}", label=f"Video {i}", ext="mp4",
                                  direct_url=video_url, http_headers=_IG_HEADERS, thumbnail=display_url))
            formats.append(Format(id=f"audio_{i}", label=f"Audio {i}", ext="mp3",
                                  direct_url=video_url, http_headers=_IG_HEADERS, needs_audio_extract=True,
                                  filesize=int(node_dur * 24000) if node_dur else None))
        elif display_url:
            formats.append(Format(id=f"image_{i}", label=f"Image {i}", ext="jpg",
                                  direct_url=display_url, http_headers=_IG_HEADERS, thumbnail=display_url))
    if not formats:
        raise ValueError("Could not extract media from this Instagram carousel.")
    return MediaInfo(title=title, thumbnail=thumbnail, platform="instagram_post", formats=formats)


def _make_product_carousel(carousel_media: list, title: str, thumbnail: str) -> MediaInfo:
    formats: list[Format] = []
    for i, item in enumerate(carousel_media, 1):
        versions = item.get("video_versions") or []
        video_url = versions[0].get("url") if versions else None
        img_candidates = (item.get("image_versions2") or {}).get("candidates") or []
        img_url = (img_candidates[0].get("url") if img_candidates else "") or ""
        if video_url:
            item_dur = item.get("video_duration") or 0
            formats.append(Format(id=f"video_{i}", label=f"Video {i}", ext="mp4",
                                  direct_url=video_url, http_headers=_IG_HEADERS, thumbnail=img_url))
            formats.append(Format(id=f"audio_{i}", label=f"Audio {i}", ext="mp3",
                                  direct_url=video_url, http_headers=_IG_HEADERS, needs_audio_extract=True,
                                  filesize=int(item_dur * 24000) if item_dur else None))
        elif img_url:
            formats.append(Format(id=f"image_{i}", label=f"Image {i}", ext="jpg",
                                  direct_url=img_url, http_headers=_IG_HEADERS, thumbnail=img_url))
    if not formats:
        raise ValueError("Could not extract media from this Instagram carousel.")
    return MediaInfo(title=title, thumbnail=thumbnail, platform="instagram_post", formats=formats)
