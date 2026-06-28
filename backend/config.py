"""
Platform IDs & query hashes — Ripple's only "magic values".

These are the public identifiers the official websites send with their own
requests. They are stable most of the time, but a platform **MAY** rotate one,
which can make that single platform stop working. If that happens, update the
matching value below — see the "Updating platform IDs" section in the README for
exactly how to find the new value for each platform.

Editing rule: only change the text **between the quotes**. Keep the quotes.
"""

# ── Instagram ────────────────────────────────────────────────────────────────
# APP_ID  : the X-IG-App-ID header value (Instagram's public web app id)
# DOC_ID  : the GraphQL persisted-query id that returns a post's media
INSTAGRAM_APP_ID = "936619743392459"
INSTAGRAM_DOC_ID = "10015901848480474"

# ── Twitch ───────────────────────────────────────────────────────────────────
# CLIENT_ID           : Twitch's public web-player Client-ID
# VIDEO_METADATA_HASH : GraphQL persisted-query hash for VOD metadata (title, etc.)
# SHARE_CLIP_HASH     : GraphQL persisted-query hash for clip playback
TWITCH_CLIENT_ID = "ue6666qo983tsx6so1t0vnawi233wa"
TWITCH_VIDEO_METADATA_HASH = "45111672eea2e507f8ba44d101a61862f9c56b11dee09a15634cb75cb9b9084d"
TWITCH_SHARE_CLIP_HASH = "0a02bb974443b576f5579aab0fef1d4b7f44e58a8a256f0c5adfead0db70640f"

# ── YouTube ──────────────────────────────────────────────────────────────────
# Ripple poses as the Android VR (Oculus) app, which returns unthrottled streams.
# CLIENT_VERSION moves when the app updates; bump it if YouTube starts failing.
YOUTUBE_CLIENT_NAME = "ANDROID_VR"
YOUTUBE_CLIENT_NAME_ID = "28"
YOUTUBE_CLIENT_VERSION = "1.65.10"
YOUTUBE_USER_AGENT = (
    "com.google.android.apps.youtube.vr.oculus/1.65.10 "
    "(Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"
)

# ── TikTok ───────────────────────────────────────────────────────────────────
# TikTok needs no IDs — Ripple reads the data embedded in the public video page.
