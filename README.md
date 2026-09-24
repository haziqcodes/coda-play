# 🎵 Coda

> **Paste any video URL → get the audio → play it as an ad-free playlist.**
> A local, YouTube-Playlist-style web app built **only for audio/songs**.
> 100% free · 100% local — no accounts, no API keys, no paid services, no ads.

<!-- replace `mohdhaziq-work` below with your real GitHub username -->
[![CI](https://github.com/haziqcodes/coda-play/actions/workflows/ci.yml/badge.svg)](https://github.com/haziqcodes/coda-play/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-1000%2B%20sites-green.svg)](https://github.com/yt-dlp/yt-dlp)

---

## ✨ Features

| # | Feature | How it works |
|---|---------|--------------|
| 1 | **Paste any social video URL** | YouTube, Instagram Reels, TikTok, X/Twitter, Facebook, +1000 more (via [yt-dlp](https://github.com/yt-dlp/yt-dlp)) |
| 2 | **Long & short videos** | 3-second Reels to 3-hour uploads — both work |
| 3 | **Audio extraction** | Converted to **MP3 (192 kbps)** with `ffmpeg`, stored locally |
| 4 | **Playlist** | Add / remove / **drag-to-reorder** / rename — persisted in `data/playlist.json` |
| 5 | **Ad-free playback** | Audio lives on your machine, played by HTML5 `<audio>` — **zero ads, ever** |
| 6 | **One song at a time** | Exactly **one audio player** exists. The next song starts *only* when the current one has **fully ended** — overlap is impossible by design |
| 7 | **Repeat control (your choice)** | 🔁 button (or `R`): **OFF** = stop when playlist ends · **ALL** = loop forever · **ONE** = loop current song |
| 8 | **Legal-safe design** | Personal-use only; no redistribution features; clear legal policy below |

**Player:** seek bar · volume · live progress · "now playing" highlight · thumbnails ·
per-track & total duration · keyboard shortcuts (`Space`, `Ctrl+←/→`, `R`).

---

## 📦 Repo structure

```
coda-play/
├── server.py            # Flask backend: URL ingest, yt-dlp + ffmpeg, playlist API, streaming
├── requirements.txt     # flask + yt-dlp (free, pip)
├── Makefile             # make install / run / test / lint / docker
├── Dockerfile           # one-command container build (ffmpeg included)
├── docker-compose.yml
├── LICENSE              # MIT
├── .editorconfig
├── .github/
│   ├── workflows/ci.yml        # CI: lint + tests on 3 Python versions
│   ├── dependabot.yml          # weekly auto dependency updates
│   ├── ISSUE_TEMPLATE/         # bug report + feature request templates
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── CONTRIBUTING.md
│   └── CODE_OF_CONDUCT.md
├── ai/
│   └── handoff.md       # AI-agent handoff (rendered at /ai, noindex) — read it before coding here
├── static/
│   ├── index.html       # single-page UI
│   ├── app.js           # player logic (single-audio rule, repeat modes, drag & drop)
│   └── style.css        # light premium theme (monochrome + #1a73e8)
├── tests/
│   └── test_api.py      # pytest suite
└── data/                # (auto-created, git-ignored) your private library
    ├── playlist.json
    ├── tracks/*.mp3
    └── thumbs/*.jpg
```

---

## 🚀 Setup — step by step (all free)

### 1. Prerequisites
**Python 3.9+** and **ffmpeg** (both free).

| OS | Python | ffmpeg |
|----|--------|--------|
| Windows | [python.org](https://www.python.org/downloads/) — ✅ tick "Add to PATH" | `winget install Gyan.FFmpeg` |
| macOS | `brew install python` | `brew install ffmpeg` |
| Linux | `sudo apt install python3 python3-venv` | `sudo apt install ffmpeg` |
| Android (Termux) | `pkg install python` | `pkg install ffmpeg` |

### 2. Get the code
```bash
git clone https://github.com/haziqcodes/coda-play.git
cd coda-play
```

### 3. Install
```bash
make install        # = venv + pip install -r requirements.txt
```
<details>
<summary>Without make</summary>

```bash
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
</details>

### 4. Run
```bash
make run            # or: python server.py
```
Open **http://127.0.0.1:8000**. Done. 🎉

### 5. Use it
Paste a video URL → **➕ Add** → watch progress → click a track to play.
Drag ⋮⋮ to reorder · ✕ to remove · 🔁 (or `R`) to change repeat mode.

### Docker (optional)
```bash
docker compose up --build      # → http://localhost:8000
```

---

## ⚙️ Architecture

```
 Browser (index.html + app.js)
   │  POST /api/add {url}
   ▼
 Flask (server.py)
   │  background job (thread)
   ▼
 yt-dlp  ──►  downloads bestaudio (1000+ sites)
   │  post-processor
   ▼
 ffmpeg  ──►  MP3 192 kbps  ──►  data/tracks/<id>.mp3
   ▼
 playlist.json updated ──► browser polls /api/job/<id>
   ▼
 Playback: <audio src="/audio/<id>.mp3">  (single player, range streaming = instant seek)
```

Design decisions:
- **One `<audio>` element** → next track triggered only by `ended` (no overlap, ever).
- **Range requests** on `/audio/...` → instant seeking.
- **Jobs + polling** → long videos never freeze the UI; live % progress.
- **Everything in `data/`** → copy it = backup; delete it = clean slate.
- **Handoff discipline** → `ai/handoff.md` (hidden at `/ai`, noindex) always carries
  the current project state, so the next human or AI agent can pick up instantly.

---

## ⚖️ Legal & rights (read once)

Coda is a **personal-use** player. To stay on the right side of the law:

1. **Personal, non-commercial use only.** **Do not redistribute, upload, or share** extracted audio.
2. **Only extract content you have rights to:** your own videos, **Creative Commons** content (check the CC badge), or content with the creator's permission.
3. **Respect platform Terms of Service.** Downloading from YouTube/Instagram may violate their ToS — for commercial music, official licensed services are the safe route. Coda is **not** a piracy tool.
4. **Credit artists** when re-using CC-licensed audio (attribution, share-alike).
5. This repo **deliberately has no** batch-export / sharing features — by design.

---

## 🌐 Free hosting options

| Option | Cost | Notes |
|--------|------|-------|
| Your PC / laptop | free | Recommended — private & instant |
| Android (Termux) | free | Phone becomes a pocket jukebox over Wi-Fi |
| Free VPS (Oracle Cloud Free Tier) | $0 | Run via `gunicorn -w 1 --threads 8 -b 0.0.0.0:8000 server:app` + Caddy/Nginx + HTTPS |
| Raspberry Pi / old PC | free | 24×7 home jukebox on LAN |

---

## 🧪 Development

```bash
make test     # pytest suite
make lint     # flake8
```
Contributing? Read [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).
Found a bug? Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md).

## 📄 License
[MIT](LICENSE) — use it, fork it, learn from it. (The legal policy above still applies to *what you extract*.)
