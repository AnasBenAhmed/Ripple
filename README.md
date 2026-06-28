<!-- ============ HEADER BANNER ============ -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:E11B22,100:E0A82E&height=200&section=header&text=Ripple&fontSize=80&fontColor=ffffff&fontAlignY=38&desc=Video%20%26%20Audio%20Downloader%20%E2%80%94%20no%20accounts,%20no%20limits&descSize=16&descAlignY=60&descColor=ffffff" width="100%"/>

<!-- ============ BADGES ============ -->
<p align="center">
  <img src="https://img.shields.io/badge/No%20Login%20Required-E11B22?style=for-the-badge&logo=incognito&logoColor=white"/>
  &nbsp;
  <img src="https://img.shields.io/badge/Built%20From%20Scratch-E0A82E?style=for-the-badge&logo=rocket&logoColor=white"/>
  &nbsp;
  <img src="https://img.shields.io/badge/No%20yt--dlp%20Library-181717?style=for-the-badge&logo=python&logoColor=white"/>
</p>

<!-- ============ ANIMATED TAGLINE ============ -->
<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=13&duration=2500&pause=99999&color=FFFFFF&center=true&vCenter=true&width=720&height=30&lines=Paste+a+link.+Pick+a+format.+Download.+That's+it.&repeat=false" alt="Tagline"/>
</p>

<!-- ============ PLATFORM ROW ============ -->
<p align="center">
  <img src="https://img.shields.io/badge/YouTube-FF0000?style=flat-square&logo=youtube&logoColor=white"/>
  <img src="https://img.shields.io/badge/Instagram-E4405F?style=flat-square&logo=instagram&logoColor=white"/>
  <img src="https://img.shields.io/badge/TikTok-000000?style=flat-square&logo=tiktok&logoColor=white"/>
  <img src="https://img.shields.io/badge/Twitch-9146FF?style=flat-square&logo=twitch&logoColor=white"/>
</p>

<!-- divider -->
<img src="https://capsule-render.vercel.app/api?type=rect&color=0:E11B22,100:E0A82E&height=4" width="100%"/>

<!-- ============ ABOUT ============ -->
## <img src="https://media.giphy.com/media/hvRJCLFzcasrR4ia7z/giphy.gif" width="28"> About

**Ripple** is a self-hosted video &amp; audio downloader for **YouTube, Instagram, TikTok, and Twitch**. Paste a link, choose a quality, and download — no sign-in, no watermarks, no third-party services.

It's built **from scratch**: a fast Python/FastAPI backend that talks directly to each platform's own endpoints, paired with a clean Next.js queue-based UI. No `yt-dlp` Python library, no download wrappers — just raw HTTP and `ffmpeg`.

```js
const ripple = {
  backend:    ["Python", "FastAPI", "httpx", "ffmpeg"],
  frontend:   ["Next.js", "React", "TypeScript"],
  platforms:  ["YouTube", "Instagram", "TikTok", "Twitch"],
  philosophy: "no accounts, no limits, no bloat",
};
```

<!-- divider -->
<img src="https://capsule-render.vercel.app/api?type=rect&color=0:E0A82E,100:E11B22&height=4" width="100%"/>

<!-- ============ FEATURES ============ -->
## ✨ Features

- 🎬 **Multi-platform** — YouTube videos &amp; Shorts, Instagram Reels / Posts / Carousels, TikTok, Twitch Clips &amp; VODs
- 🎚️ **Quality picker** — MP4 at 1080p / 720p / 480p / 360p, or extract **MP3 audio**
- ⚡ **Fast downloads** — bypasses YouTube's per-connection CDN throttling with chunked range requests
- 📊 **Live progress** — real-time speed and percentage for every item in the queue
- 🔓 **No login** — pulls public content straight from each platform's web API
- 🧱 **From scratch** — no `yt-dlp` library, no download wrappers, just HTTP + `ffmpeg`

<!-- divider -->
<img src="https://capsule-render.vercel.app/api?type=rect&color=0:E11B22,100:E0A82E&height=4" width="100%"/>

<!-- ============ SUPPORTED ============ -->
## 🌐 Supported Platforms

<table>
  <tr>
    <td width="50%" valign="top">
      <h3>▶️ YouTube</h3>
      <p>Videos &amp; Shorts<br/>MP4 — 1080p / 720p / 480p / 360p<br/>MP3 audio extraction</p>
    </td>
    <td width="50%" valign="top">
      <h3>📸 Instagram</h3>
      <p>Reels, Posts &amp; Carousels<br/>Video (MP4) + Audio (MP3)<br/>Image downloads</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <h3>🎵 TikTok</h3>
      <p>Videos — watermark-free<br/>MP4 + MP3 audio</p>
    </td>
    <td width="50%" valign="top">
      <h3>🟣 Twitch</h3>
      <p>Clips &amp; VODs<br/>MP4 video</p>
    </td>
  </tr>
</table>

<!-- divider -->
<img src="https://capsule-render.vercel.app/api?type=rect&color=0:E0A82E,100:E11B22&height=4" width="100%"/>

<!-- ============ TECH STACK ============ -->
## 🧰 Tech Stack

<p align="center">
  <b>Backend</b><br/>
  <img src="https://skillicons.dev/icons?i=python,fastapi&theme=light" />
</p>
<p align="center">
  <b>Frontend</b><br/>
  <img src="https://skillicons.dev/icons?i=nextjs,react,ts,css&theme=light" />
</p>
<p align="center">
  <b>Media</b><br/>
  <img src="https://img.shields.io/badge/ffmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white"/>
</p>

<!-- divider -->
<img src="https://capsule-render.vercel.app/api?type=rect&color=0:E11B22,100:E0A82E&height=4" width="100%"/>

<!-- ============ GETTING STARTED ============ -->
## 🚀 Getting Started

**Prerequisites**

- Python **3.11+**
- Node.js **18+**
- [`ffmpeg`](https://ffmpeg.org/download.html) installed and on your `PATH`

### 1 · Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --port 8006
# → http://localhost:8006
```

### 2 · Frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

Open **http://localhost:3000**, paste a link, and hit **Add to Queue**.

<!-- divider -->
<img src="https://capsule-render.vercel.app/api?type=rect&color=0:E0A82E,100:E11B22&height=4" width="100%"/>

<!-- ============ HOW IT WORKS ============ -->
## ⚙️ How It Works

Each platform has its own **extractor** that resolves a public URL into direct media streams using that platform's own web endpoints:

- **YouTube** → InnerTube player API (ANDROID_VR client), then merges the best video + audio streams with `ffmpeg`. A local CDN proxy fetches the streams in 10 MB range chunks to dodge per-connection throttling.
- **Instagram** → web GraphQL persisted query with the public `X-IG-App-ID`, returning media for reels, posts, and carousels without any login.
- **TikTok / Twitch** → direct resolution of the public stream URLs.

The FastAPI backend streams the result straight to your browser while reporting live progress; `ffmpeg` handles muxing and MP3 extraction on the fly — nothing is ever written to disk on the server.

<!-- ============ DISCLAIMER ============ -->
> [!NOTE]
> Ripple is a personal project for downloading content you have the right to access. Respect each platform's Terms of Service and creators' copyright.

<!-- ============ FOOTER WAVE ============ -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:E0A82E,100:E11B22&height=160&section=footer&text=Built%20by%20Anas%20Ben%20Ahmed&fontSize=22&fontColor=ffffff&fontAlignY=72&desc=Paste%20·%20Pick%20·%20Download&descSize=14&descAlignY=88&descColor=ffffff" width="100%"/>
