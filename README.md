# Ripple — Video & Audio Downloader

Download videos and audio from YouTube, Instagram, TikTok, and Twitch.
Built from scratch — no yt-dlp, no third-party download libraries.

## Requirements

- Python 3.11+
- Node.js 18+
- ffmpeg installed and on PATH ([ffmpeg.org](https://ffmpeg.org/download.html))

## Run

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

## Supported URLs

| Platform  | What works                          |
|-----------|-------------------------------------|
| YouTube   | Videos — MP4 (1080p/720p/480p/360p) + MP3 |
| Instagram | Posts, Reels                        |
| TikTok    | Videos (watermark-free)             |
| Twitch    | VODs (`/videos/...`) + Clips        |
