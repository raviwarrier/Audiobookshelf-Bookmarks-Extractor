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
        PORT: 13379, // Web UI port
        // Server Admin Configurations (automatically provided to connected clients):
        SIDECAR_URL: 'http://localhost:13380', // Internal address for the sidecar service
        USE_BACKEND_PROXY: 'true', // Bypasses browser CORS errors for all clients
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
        PORT: 13380, // Sidecar & Interceptor proxy port
        SIDECAR_PORT: 13380,
        ABS_TARGET_SERVER: 'http://192.168.68.102:13378', // Upstream ABS URL (use Host LAN IP like 192.168.x.x if ABS runs in Docker)
        VOLUME_DIR: '/srv/ssd/Bookshelf/advplyr-bookshelf/bookmarks', // Output directory for bookmarks
        AUDIOBOOKS_PATH: '/srv/ssd/Bookshelf/Audiobooks', // Host path to audiobooks
        PATH_MAPPINGS: '/audiobooks:/srv/ssd/Bookshelf/Audiobooks,/summaries:/srv/ssd/Bookshelf/Summaries' // Docker container:host directory mappings
      }
    }
  ]
};
