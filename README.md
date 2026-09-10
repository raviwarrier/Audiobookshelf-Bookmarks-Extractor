# Audiobookshelf Bookmarks Extractor

**Version 1.0**  
Backend app for the bookmarks you create on the ABS Mobile app.

---

## What It Does

Audiobookshelf Bookmarks Extractor extracts audio clips corresponding to your bookmarks or active listening positions in [Audiobookshelf](https://www.audiobookshelf.org/), transcribes them to text using faster-whisper or Vosk, and stores them neatly structured under each user's directory (`{username}/bookmarks/{book_title}/`).

### Architecture Notice
This project is designed primarily as the **backend service** for the bookmark extractor pipeline. A companion **native Android Kotlin app** is currently being developed to serve as the mobile frontend, letting you tap a button to trigger extraction and transcription directly from your bookmark positions. 

In addition to serving as a backend API, this application also includes a built-in web frontend that you can use directly from any browser if needed.

---

## Security & Privacy Assurance

- **Zero Persistent Storage**: Your Audiobookshelf credentials, API tokens, and passwords are encrypted in-memory using an ephemeral AES-256 session key.
- **No Disk Storage**: Tokens and secrets are **never** written to `localStorage`, cookies, IndexedDB, or server-side database files.
- **Session-Only Lifetime**: All keys and credentials vanish immediately when you refresh the page, close the browser tab, or click Disconnect.

---

## Share with Your Users

If your users want to use this app (and in the future, the companion Android app), they will need to enter their **API key** (recommended) or their **username and password**.

Here is a simple step-by-step instruction that you can share with your users on how to obtain their API key:

### How to Obtain Your API Key
*(Best done on desktop browser)*

1. Open your Audiobookshelf server URL in your browser and log into your account.
2. Click on your **User Profile / Avatar** icon in the navigation bar.
3. In your account/profile settings, locate the **API Token** section.
4. Click **Generate Token** (or copy your existing token).
5. Copy the generated key and paste it into the **API Key** field in the app.

---

## Screenshots

### Main Screen
![Main Screen](public/app_screenshots/main_screen.png)

### Snippets View
![Snippets View](public/app_screenshots/snippets.png)

---

## Prerequisites

### General Requirements
- **Audiobookshelf Server** (v2.0+) up and running with audiobooks and bookmarks.
- **Audio Files Access**: Direct local directory access or Docker volume mount to your Audiobookshelf audio files so the extractor can slice segments directly from source files.

### If running via Docker (Recommended)
- **Docker Engine** (v20.10+) and **Docker Compose** (v2.0+).
- *All runtimes, tools (FFmpeg), and speech-to-text models are automatically packaged and pre-configured inside the container.*

### If running directly on host (NPM / PM2)
- **Node.js**: `v18.0.0` or higher (with `npm`).
- **Python**: `v3.10` or higher (with `pip` and `venv`).
- **FFmpeg**: Mandatory system tool for audio slicing, segment extraction, and audio transcription conversion:
  - *Ubuntu / Debian*: `sudo apt-get install -y ffmpeg`
  - *macOS (Homebrew)*: `brew install ffmpeg`
  - *Arch Linux*: `sudo pacman -S ffmpeg`
  - *Fedora / RHEL*: `sudo dnf install -y ffmpeg`

---

## Installation

Default application port: **13379**

### 1. Docker (Recommended)

Clone the repository and run via Docker Compose (FFmpeg, Whisper, and Vosk dependencies are automatically containerized):

```bash
git clone https://github.com/raviwarrier/Audiobookshelf-Bookmarks-Extractor.git
cd Audiobookshelf-Bookmarks-Extractor

docker compose up -d --build
```

The service will be accessible at `http://[your ip:port/proxied url]`.

### 2. NPM (Direct)

```bash
# 1. Install required system tools (FFmpeg for audio processing)
sudo apt-get update && sudo apt-get install -y ffmpeg

# 2. Clone repository
git clone https://github.com/raviwarrier/Audiobookshelf-Bookmarks-Extractor.git
cd Audiobookshelf-Bookmarks-Extractor

# 3. Install dependencies
npm install
pip install -r requirements.txt

# 4. Start backend & dev frontend
npm run dev
```

### 3. PM2 (Process Manager)

The project includes an `ecosystem.config.cjs` configuration that manages both the web server (`abs-extractor-web` on port 13379) and the Python sidecar (`abs-extractor-sidecar` on port 8000).

```bash
# 1. Install required system tools (FFmpeg for audio processing)
sudo apt-get update && sudo apt-get install -y ffmpeg

# 2. Clone repository
git clone https://github.com/raviwarrier/Audiobookshelf-Bookmarks-Extractor.git
cd Audiobookshelf-Bookmarks-Extractor

# 3. Install dependencies and build
npm install
npm run build
pip install -r requirements.txt

# 4. Start all services using PM2 Ecosystem
pm2 start ecosystem.config.cjs
pm2 save

# Optional: To start on boot
pm2 startup
```

---

## Updating

### 1. Docker
```bash
git pull origin main
docker compose down
docker compose up -d --build
```

### 2. NPM
```bash
git pull origin main

# Ensure system tools are up to date
sudo apt-get update && sudo apt-get install --only-upgrade -y ffmpeg

npm install
npm run build
pip install -U -r requirements.txt
```

### 3. PM2
```bash
git pull origin main

# Ensure system tools are up to date
sudo apt-get update && sudo apt-get install --only-upgrade -y ffmpeg

npm install
npm run build
pip install -U -r requirements.txt
pm2 restart ecosystem.config.cjs --update-env
```

---

## CORS Configuration Warning

> ⚠️ **Caution for Server Admins**: If you access Audiobookshelf across different domains or ports without using the built-in server proxy, your reverse proxy or tunnel **must** enable Cross-Origin Resource Sharing (CORS) headers. 

*(Note: If you keep **Backend Server Proxy** enabled in the web app, requests are relayed server-to-server and will bypass browser CORS automatically.)*

If connecting directly from a browser or external client, configure your reverse proxy:

### Nginx
Add to your `location` block:
```nginx
location / {
    if ($request_method = 'OPTIONS') {
        add_header 'Access-Control-Allow-Origin' '*' always;
        add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS, PUT, DELETE' always;
        add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, Accept' always;
        add_header 'Content-Length' 0;
        add_header 'Content-Type' 'text/plain; charset=utf-8';
        return 204;
    }
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Allow-Methods' 'GET, POST, OPTIONS, PUT, DELETE' always;
    add_header 'Access-Control-Allow-Headers' 'Authorization, Content-Type, Accept' always;
    proxy_pass http://localhost:13378;
}
```

### Traefik
In your Docker Compose labels:
```yaml
labels:
  - "traefik.http.middlewares.abs-cors.headers.accesscontrolallowmethods=GET,POST,OPTIONS,PUT,DELETE"
  - "traefik.http.middlewares.abs-cors.headers.accesscontrolalloworiginlist=*"
  - "traefik.http.middlewares.abs-cors.headers.accesscontrolallowheaders=Authorization,Content-Type,Accept"
  - "traefik.http.routers.abs.middlewares=abs-cors"
```

### Caddy
In your `Caddyfile`:
```caddyfile
your-abs-domain.com {
    @cors_preflight method OPTIONS
    handle @cors_preflight {
        header Access-Control-Allow-Origin "*"
        header Access-Control-Allow-Methods "GET, POST, OPTIONS, PUT, DELETE"
        header Access-Control-Allow-Headers "Authorization, Content-Type, Accept"
        respond "" 204
    }
    header Access-Control-Allow-Origin "*"
    reverse_proxy localhost:13378
}
```

### Cloudflare Tunnels (`cloudflared`)
1. In Cloudflare Zero Trust Dashboard, navigate to **Networks** > **Tunnels** > select your tunnel.
2. Under **Public Hostname**, edit your Audiobookshelf hostname.
3. Expand **Additional application settings** > **HTTP Response Headers** and add:
   - `Access-Control-Allow-Origin`: `*`
   - `Access-Control-Allow-Methods`: `GET, POST, OPTIONS, PUT, DELETE`
   - `Access-Control-Allow-Headers`: `Authorization, Content-Type, Accept`

---

## API Usage & Examples

All API endpoints accept Bearer token authentication and can be called directly by external applications (such as the companion Android Kotlin app).

### 1. Health Check
```bash
curl -X GET http://[your ip:port/proxied url]/api/health
```
Response:
```json
{
  "status": "healthy",
  "service": "Audiobookshelf Bookmarks Extractor",
  "version": "1.0"
}
```

### 2. Extract Active Listening Bookmark
Extracts an audio snippet and generates a transcript from the current listening session:
```bash
curl -X POST http://[your ip:port/proxied url]/api/snippet \
  -H "Authorization: Bearer <ABS_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"duration": 60}'
```

Response:
```json
{
  "status": "success",
  "message": "Bookmark audio extracted and transcribed successfully",
  "snippet": {
    "book_title": "Project Hail Mary: A Novel",
    "author": "Andy Weir",
    "chapter": "Chapter 4",
    "timestamp": "20260910_103000",
    "date_time": "2026-09-10 10:30:00",
    "start_time": 1420.5,
    "current_time": 1450.5,
    "bookmarked_duration": "00:24:10 (1450 seconds)",
    "duration": 60,
    "snippet_length": "60 seconds",
    "transcript": "- Date / Time: 2026-09-10 10:30:00\n- Book Title: Project Hail Mary: A Novel\n- Author(s): Andy Weir\n- Bookmarked Duration: 00:24:10 (1450 seconds)\n- Snippet Length: 60 seconds\n- Chapter: Chapter 4\n\nI am in a spaceship and I am waking up...",
    "audio_url": "/bookmarks/username/Project_Hail_Mary/20260910_103000.mp3",
    "md_url": "/bookmarks/username/Project_Hail_Mary/20260910_103000.md"
  }
}
```

---

## Transcription Metadata Format

Every generated markdown document (`.md`), metadata file (`.json`), and API transcript payload includes the following structured metadata at the beginning of the text:

- **Date / Time**: Timestamp when the bookmark/snippet was captured (`YYYY-MM-DD HH:MM:SS`)
- **Book Title: Sub-Title**: Full title including subtitle if present
- **Author(s)**: Book author name(s)
- **Bookmarked Duration**: Exact position in `HH:MM:SS (SSSS seconds)` format
- **Snippet Length**: Length of audio clip in seconds
- **Chapter**: Chapter number and name (or `N/A` if unavailable)
- **Transcribed Text**: Whisper / Vosk transcription body

Example Markdown Output:

```markdown
---
title: "Project Hail Mary: A Novel"
author: "Andy Weir"
chapter: "Chapter 4"
timestamp: "20260910_103000"
date_time: "2026-09-10 10:30:00"
bookmarked_duration: "00:24:10 (1450 seconds)"
duration: 60
snippet_length: "60 seconds"
transcription_engine: "faster-whisper"
---

# Project Hail Mary: A Novel

- Date / Time: 2026-09-10 10:30:00
- Book Title: Project Hail Mary: A Novel
- Author(s): Andy Weir
- Bookmarked Duration: 00:24:10 (1450 seconds)
- Snippet Length: 60 seconds
- Chapter: Chapter 4

---

## Transcribed Text

I am in a spaceship and I am waking up...
```

### 3. Extract from Specific Bookmark Timestamp
```bash
curl -X POST http://[your ip:port/proxied url]/api/snippet \
  -H "Authorization: Bearer <ABS_API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "custom_offset": 850,
    "duration": 45
  }'
```

### 4. List User Bookmarks
Lists all extracted snippets and transcripts for the authenticated user:
```bash
curl -X GET http://[your ip:port/proxied url]/api/bookmarks \
  -H "Authorization: Bearer <ABS_API_TOKEN>"
```

### 5. Stream or Download Audio File
```bash
curl -O http://[your ip:port/proxied url]/bookmarks/username/Project_Hail_Mary/20260910_103000.mp3
```

---

## Vibe Coding Disclaimer

This codebase was crafted and refined using conversational AI-assisted "vibe coding". While it is designed to be lean, functional, and practical for homelab use, review the code to ensure it meets your specific environment, deployment, and security requirements before deploying into critical production workflows.

---

## License (MIT in Plain English)

You are completely free to use, copy, modify, merge, publish, distribute, and even sell copies of this software for personal, educational, or commercial purposes. 

The only conditions are:
1. Keep the original copyright notice and permission notice in any copy you distribute.
2. The software is provided as-is, without warranty of any kind. If something breaks or doesn't work as expected, the authors and contributors are not liable.
