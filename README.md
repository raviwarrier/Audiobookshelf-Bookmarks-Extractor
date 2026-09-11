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

## Ports & Network Architecture

The application is carefully configured to avoid port conflicts with existing homelab services and your Audiobookshelf server:

| Port | Service | Default Component | Purpose & Description |
| :--- | :--- | :--- | :--- |
| **`13378`** | **Audiobookshelf Server (Target Only)** | External ABS Instance | **ABS Default Port**: Used strictly as the *target destination* URL for the sidecar and web proxy to connect to Audiobookshelf. **The extractor never listens or binds to port 13378.** |
| **`13380`** *(or `13377`)* | **FastAPI Sidecar & Interceptor Proxy** | Python Backend (`abs-extractor-sidecar`) | **Primary API & Interceptor Port**: Slices audio (`ffmpeg`), runs AI transcription (faster-whisper/Vosk), and intercepts bookmark events (`POST /api/me/item/:id/bookmark`). Also transparently relays all other ABS traffic (`/{path:path}`) to the upstream ABS server. |
| **`13379`** *(or `13376`)* | **Web Dashboard & Server-Side Proxy** | Node.js / Express (`abs-extractor-web`) | **User Interface & CORS Proxy**: Hosts the web dashboard, listening session visualizer, integrated audio player, and transcript reader. Relays API calls through `/api/proxy/abs` to bypass browser CORS restrictions. |
| **`3000` & `8080`** | *(Developer & Cloud Ingress Only)* | Dev Containers | **Not used on your production host server**: Port 8080 has been removed from `Dockerfile`, and port 3000 is reserved only for local development (`npm run dev`). On your production host server, only `13379` and `13380` (or your custom chosen ports) are used. |

---

## Interactive Setup Wizard (CLI)

The repository includes an interactive configuration wizard that guides you through setting your Audiobookshelf URL, storage directory (`VOLUME_DIR`), and network ports:

```bash
# Run anytime after cloning (or to reconfigure later):
./setup.sh

# Or via npm:
npm run setup

# Or via Python:
python3 setup.py
```

The wizard prompts you for:
1. **Audiobookshelf Target Server URL** (e.g. `http://localhost:13378` or `http://audiobookshelf:80`)
2. **Bookmarks & Volume Storage Directory** (`VOLUME_DIR`, e.g. `/srv/ssd/Appdata/local/bookmarks` or `./bookmarks`)
3. **Audiobooks Media Library Directory** (Host path for read-only mount)
4. **FastAPI Sidecar Port** (default `13380`, or alternative `13377`; validates that `13378` is not used)
5. **Web Dashboard Port** (default `13379`, or alternative `13376`)
6. **Whisper Transcription Model** (`base.en`, `tiny.en`, `small.en`, or `medium.en`)

It writes a local `.env` file with restrictive permissions (`600`) and automatically ensures that the file is protected by `.gitignore`.

---

## Privacy & Security: Secrets & Environment Protection

All configuration values, server URLs, credentials, and storage directories you configure are protected:
- **Strictly Git-Ignored**: `.env`, `.env.*`, `credentials*`, and `*token*` are declared in `.gitignore`.
- **No Secrets in Code**: The repository only tracks `.env.example` with dummy template values. Your actual `.env` will never be pushed or committed to Git.
- **Media & Transcripts Privacy**: Extracted audio clips (`.mp3`), transcripts (`.md`), and JSON metadata in `bookmarks/` and `data/` are also strictly git-ignored.

---

## Installation

### 1. Docker (Recommended)

Clone the repository and run the setup wizard to configure your directories and ports:

```bash
git clone https://github.com/raviwarrier/Audiobookshelf-Bookmarks-Extractor.git
cd Audiobookshelf-Bookmarks-Extractor

# Run interactive configuration
./setup.sh

# Start containers
docker compose up -d --build
```

The service will be accessible at `http://[your ip:port/proxied url]`.

### 2. NPM (Direct)

```bash
# 1. Install required system tools (FFmpeg & Python venv)
sudo apt-get update && sudo apt-get install -y ffmpeg python3-venv

# 2. Clone repository
git clone https://github.com/raviwarrier/Audiobookshelf-Bookmarks-Extractor.git
cd Audiobookshelf-Bookmarks-Extractor

# 3. Create and activate a Python virtual environment (recommended to isolate dependencies)
python3 -m venv venv
source venv/bin/activate

# 4. Install dependencies
npm install
pip install -r requirements.txt

# 5. Start backend & dev frontend
npm run dev
```

### 3. PM2 (Process Manager)

The project includes an `ecosystem.config.cjs` template with simple placeholder paths and `exec_mode: 'fork'`. This avoids any fragile path-guessing code, works cleanly whether placed in the repo or inside a central folder like `/home/pi`, and eliminates unnecessary clustering overhead.

#### Quick Setup:
```bash
# 1. Install required system tools (FFmpeg & Python venv)
sudo apt-get update && sudo apt-get install -y ffmpeg python3-venv

# 2. Clone repository (example path: /srv/ssd/Appdata/local/Audiobookshelf-Bookmarks-Extractor)
git clone https://github.com/raviwarrier/Audiobookshelf-Bookmarks-Extractor.git
cd Audiobookshelf-Bookmarks-Extractor

# 3. Create Python virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. Install Node dependencies and build frontend
npm install
npm run build
```

#### Configuring `ecosystem.config.cjs`:
Open `ecosystem.config.cjs` (either in the app directory or in `/home/pi/ecosystem.config.cjs`) and configure the placeholder paths at the top:

```javascript
// --- Configure your installation paths here ---
const APP_DIR = '/srv/ssd/Appdata/local/Audiobookshelf-Bookmarks-Extractor';
const PYTHON_PATH = `${APP_DIR}/venv/bin/python3`; // Set to 'python3' if not using a venv

module.exports = {
  apps: [
    // 1. Web Dashboard & Server-Side Proxy
    {
      name: 'abs-extractor-web',
      cwd: APP_DIR,
      script: `${APP_DIR}/dist/server.cjs`,
      exec_mode: 'fork',
      autorestart: true,
      env: {
        NODE_ENV: 'production',
        PORT: 13379 // Web UI port
      }
    },
    // 2. Python Audio Slicing & Transcription Sidecar
    {
      name: 'abs-extractor-sidecar',
      cwd: APP_DIR,
      script: `${APP_DIR}/main.py`,
      interpreter: PYTHON_PATH,
      exec_mode: 'fork',
      autorestart: true,
      env: {
        PORT: 13380, // Sidecar & Interceptor proxy port
        SIDECAR_PORT: 13380,
        ABS_TARGET_SERVER: 'http://localhost:13378', // Your Audiobookshelf server URL
        VOLUME_DIR: '/srv/ssd/Appdata/local/bookmarks' // Output directory for bookmarks
      }
    }
  ]
};
```

#### Starting & Managing with PM2:
```bash
# Start all services using PM2 Ecosystem
pm2 start ecosystem.config.cjs
pm2 save

# Optional: To restart only these two apps if adding to an existing PM2 list in /home/pi:
pm2 restart ecosystem.config.cjs --only abs-extractor-web,abs-extractor-sidecar --update-env

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

source venv/bin/activate
pip install -U -r requirements.txt
npm install
npm run build
```

### 3. PM2
```bash
git pull origin main

# Ensure system tools are up to date
sudo apt-get update && sudo apt-get install --only-upgrade -y ffmpeg

source venv/bin/activate
pip install -U -r requirements.txt
npm install
npm run build
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

## Event-Driven Automated Bookmark Capture (Middleware Interceptor Proxy)

The sidecar supports **automated, event-driven audio clipping and transcription** via a transparent middleware interceptor proxy.

### How It Works
Since Audiobookshelf does not emit native WebSocket events when a bookmark is created, the sidecar acts as a transparent reverse proxy for Audiobookshelf:
1. Point your reverse proxy, DNS, or ABS mobile client to the sidecar (e.g. port `13380` or via your reverse proxy).
2. When the ABS mobile app creates a bookmark via `POST /api/me/item/{library_item_id}/bookmark`, the sidecar interceptor forwards the request directly to the backend ABS server (`ABS_TARGET_SERVER`).
3. The original ABS response is immediately returned to the mobile app with zero delay.
4. Concurrently, a background non-blocking worker (`process_bookmark_extraction`) clips the audio around the bookmark timestamp (`-x`/`+x` seconds) using `ffmpeg` and runs Whisper / Vosk speech-to-text transcription.
5. All other API requests, streams, and sessions are seamlessly relayed to Audiobookshelf via the catch-all transparent proxy route (`/{path:path}`).
6. Existing manual triggers (`/api/snippet`, `/api/extract`, web dashboard) continue to function identically.

### Network Flow Diagram
```
[ ABS Mobile App / Client ]
           │
           ▼
[ FastAPI Sidecar (Port 13380) ]
   ├── POST /api/me/item/:id/bookmark ──────┐
   │     │ (immediate async return)         │
   │     ▼                                  ▼
   │   Forward request to              Spawns non-blocking
   │   ABS_TARGET_SERVER (Port 13378)   Background Worker:
   │                                    - ffmpeg audio slice
   │                                    - Whisper/Vosk transcript
   │                                    - Saves to /data/{user}/bookmarks/
   │
   └── All Other Routes (/{path:path}) ────► Relayed transparently to ABS
```

---

## Configuration & Environment Variables

All settings can be specified in a `.env` file, in `docker-compose.yml`, or in `ecosystem.config.cjs`:

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `ABS_TARGET_SERVER` | `http://localhost:13378` | **Upstream Audiobookshelf Server**: The internal or external HTTP URL of your Audiobookshelf server (e.g. `http://audiobookshelf:80` in Docker). |
| `ABS_SERVER_URL` | `http://localhost:13378` | Backward-compatible fallback for `ABS_TARGET_SERVER`. |
| `PORT` | `13379` (Web) / `13380` (Sidecar) | Port on which the respective service listens. In PM2 / production, Express runs on `13379` and FastAPI on `13380`. In Vite dev mode, dev preview binds to `3000`. |
| `SIDECAR_PORT` | `13380` | Explicit override port for the FastAPI sidecar. |
| `VOLUME_DIR` | `/data` | Root output directory where generated audio clips (`.mp3`), transcripts (`.md`), and metadata (`.json`) are stored in `{username}/bookmarks/{book_title}/`. |
| `SNIPPETS_DIR` | `/data` | Backward-compatible alias for `VOLUME_DIR`. |
| `SNIPPET_DURATION` | `60` | Total length (in seconds) of the extracted audio snippet around the bookmark. |
| `SNIPPET_PRE_ROLL` | `30.0` | Number of seconds before the bookmark timestamp to begin the extracted audio clip. For a 60s duration with 30s pre-roll, the snippet captures `[bookmark - 30s]` to `[bookmark + 30s]`. |
| `WHISPER_MODEL` | `base.en` | Model size for faster-whisper (`tiny.en`, `base.en`, `small.en`, `medium.en`). Defaults to `base.en` for fast, accurate English transcription on CPUs. |
| `WHISPER_DEVICE` | `cpu` | Device for Whisper speech recognition (`cpu` or `cuda`). |
| `WHISPER_COMPUTE_TYPE` | `int8` | Inference quantization (`int8`, `float16`, `float32`). `int8` offers high performance with low memory footprint on CPU and Raspberry Pi. |
| `VOSK_MODEL_NAME` | `vosk-model-small-en-us-0.15` | Backup lightweight speech recognition model used if Whisper fails. |
| `RELOAD` | `false` | Enable live-reload for uvicorn development mode (`true`/`false`). Keep `false` in production. |

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
