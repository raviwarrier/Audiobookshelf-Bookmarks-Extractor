const fs = require('fs');
const path = require('path');

// ==============================================================================
// PM2 Ecosystem Configuration for Audiobookshelf Bookmarks Extractor
// ==============================================================================
// INSTRUCTIONS FOR USERS:
// 1. APP_DIR: Absolute path to where this repository is located on your server disk.
//    Change this if your installation path is different (e.g. '/home/pi/Audiobookshelf-Bookmarks-Extractor').
// 2. PYTHON_PATH: Absolute path to the Python executable in your virtual environment (venv).
//    Virtual Environment (venv) is the DEFAULT execution mode for this application.
//    By default, it uses '${APP_DIR}/venv/bin/python3'.
//    (The setup and update scripts automatically create this venv for you).
// 3. VOLUME_DIR: Absolute path to the output directory where audio clips & transcripts are saved.
// 4. AUDIOBOOKS_PATH: Absolute path to the directory on your host disk where audiobooks reside.
// 5. PATH_MAPPINGS: Container-to-host path mapping if Audiobookshelf is running in Docker.
// 6. ABS_TARGET_SERVER: Upstream target URL of your Audiobookshelf server.
//    IMPORTANT DOCKER NOTE: Since Audiobookshelf is almost always installed as a Docker container,
//    'http://localhost:13378' or 'http://127.0.0.1:13378' will often fail with connection refused or HTTP 502
//    because host loopback does not route into Docker container published ports.
//    ALWAYS enter your host server's LAN IP instead (e.g. 'http://192.168.68.102:13378').
// ==============================================================================

// --- Configure your installation paths here (Absolute Paths) ---
const APP_DIR = '/srv/ssd/Appdata/local/Audiobookshelf-Bookmarks-Extractor'; // Absolute path to the app directory
const DEFAULT_VENV_PYTHON = path.join(APP_DIR, 'venv', 'bin', 'python3');

// Virtual Environment (venv) is the default mode:
// Points directly to the absolute path of the venv python3 executable
const PYTHON_PATH = fs.existsSync(DEFAULT_VENV_PYTHON) ? DEFAULT_VENV_PYTHON : `${APP_DIR}/venv/bin/python3`;

// ==============================================================================
// SIDECAR NETWORK ACCESS CONFIGURATION
// Choose EXACTLY ONE of the following configurations for SIDECAR_URL:
// (Remember to keep the other methods commented out!)
//
// --- OPTION A: PUBLIC DOMAIN / REVERSE PROXY (Cloudflare, Nginx Proxy Manager, Caddy) ---
// Use this if you access your sidecar or dashboard via a reverse proxy domain.
// IMPORTANT PORT RULE FOR REVERSE PROXIES:
// - If your reverse proxy (e.g. NPM) forwards 'abs-bookmarks.raviwarrier.net' directly
//   to internal IP 192.168.68.102:13380, do NOT add ':13380' to the domain!
//   Use standard 'https://abs-bookmarks.raviwarrier.net' because the reverse proxy
//   already routes incoming traffic on standard port 443/80 into port 13380.
// - If you explicitly expose port 13380 publicly, then include ':13380'.
// const SIDECAR_URL_CONFIG = 'https://abs-bookmarks.raviwarrier.net'; // <-- [OPTION A: Reverse Proxy Domain]
//
// --- OPTION B: HOST LAN IP & PORT (Direct Home/Local Network Access) ---
// Use this if you connect to your server directly over your home Wi-Fi/LAN without reverse proxy.
// const SIDECAR_URL_CONFIG = 'http://192.168.68.102:13380'; // <-- [OPTION B: Direct LAN IP & Port]
//
// --- OPTION C: LOCAL LOOPBACK (Default & Recommended with Dashboard Backend Proxy) ---
// When USE_BACKEND_PROXY is 'true', the Web Dashboard server (port 13379) communicates
// with the sidecar locally on localhost:13380 and proxies requests seamlessly.
const SIDECAR_URL_CONFIG = 'http://localhost:13380'; // <-- [OPTION C: Localhost with Proxy]
// ==============================================================================

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
        HOST: '0.0.0.0', // Bind to all interfaces so web UI is reachable across LAN and reverse proxy
        PORT: 13379, // Web UI port
        // Server Admin Configurations (automatically provided to connected clients):
        SIDECAR_URL: SIDECAR_URL_CONFIG, // Sidecar service URL (configured in OPTION A, B, or C above)
        USE_BACKEND_PROXY: 'true', // Bypasses browser CORS errors and proxies audio/API calls for all clients
        ABS_TARGET_SERVER: 'http://192.168.68.102:13378' // Default Audiobookshelf server (use Host LAN IP for Dockerized ABS)
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
        HOST: '0.0.0.0', // Bind to all interfaces (localhost, LAN IP, docker bridge)
        PORT: 13380, // Sidecar & Interceptor proxy port
        SIDECAR_PORT: 13380,
        ABS_TARGET_SERVER: 'http://192.168.68.102:13378', // Upstream ABS URL (use Host LAN IP like 192.168.x.x if ABS runs in Docker)
        VOLUME_DIR: '/srv/ssd/Appdata/local/advplyr-bookshelf/bookmarks', // Output directory for bookmarks (auto-scans /srv/ssd/Bookshelf/... as fallback)
        AUDIOBOOKS_PATH: '/srv/ssd/Bookshelf/Audiobooks', // Host path to audiobooks
        PATH_MAPPINGS: '/audiobooks:/srv/ssd/Bookshelf/Audiobooks,/summaries:/srv/ssd/Bookshelf/Summaries' // Docker container:host directory mappings
      }
    }
  ]
};
