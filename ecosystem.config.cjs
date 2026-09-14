const fs = require('fs');
const path = require('path');

// ==============================================================================
// PM2 Configuration for Audiobookshelf Bookmarks Extractor
// ==============================================================================
// Key Settings:
// - APP_DIR: Absolute path to this repository on your server.
// - PYTHON_PATH: Path to Python in your venv (default: ${APP_DIR}/venv/bin/python3).
// - ABS_TARGET_SERVER: URL of Audiobookshelf (use LAN IP e.g. http://192.168.1.100:13378 if ABS is in Docker).
// - VOLUME_DIR: Destination directory where audio clips (.mp3) and transcripts (.md) are saved.
// - AUDIOBOOKS_PATH: Host folder where your audiobook files are stored.
// - PATH_MAPPINGS: Docker container-to-host path mapping (e.g. '/audiobooks:/host/path/Audiobooks').
// - INTERCEPT_SNIPPET_DURATION: Default audio duration (seconds) for mobile/app bookmarks.
// - INTERCEPT_PRE_ROLL: Seconds captured before the bookmark timestamp.
// ==============================================================================

const APP_DIR = '/srv/ssd/Appdata/local/Audiobookshelf-Bookmarks-Extractor';
const DEFAULT_VENV_PYTHON = path.join(APP_DIR, 'venv', 'bin', 'python3');
const PYTHON_PATH = fs.existsSync(DEFAULT_VENV_PYTHON) ? DEFAULT_VENV_PYTHON : `${APP_DIR}/venv/bin/python3`;

// SIDECAR_URL: How the Web UI connects to the Python sidecar.
// - Reverse proxy domain: 'https://abs-bookmarks.example.com' (no port if reverse proxy routes 443 -> 13380)
// - Direct LAN IP: 'http://192.168.1.100:13380'
// - Localhost (recommended with USE_BACKEND_PROXY: 'true'): 'http://localhost:13380'
const SIDECAR_URL_CONFIG = 'http://localhost:13380';

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
        HOST: '0.0.0.0',
        PORT: 13379,
        SIDECAR_URL: SIDECAR_URL_CONFIG,
        USE_BACKEND_PROXY: 'true',
        DEFAULT_ABS_URL: 'https://abs.example.com',
        ABS_TARGET_SERVER: 'http://192.168.68.102:13378'
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
        HOST: '0.0.0.0',
        PORT: 13380,
        SIDECAR_PORT: 13380,
        ABS_TARGET_SERVER: 'http://192.168.68.102:13378',
        INTERCEPT_SNIPPET_DURATION: 60, // Total clip length for intercepted bookmarks (seconds)
        INTERCEPT_PRE_ROLL: 30,         // Seconds to capture before the bookmark
        VOLUME_DIR: '/srv/ssd/Appdata/local/advplyr-bookshelf/bookmarks',
        AUDIOBOOKS_PATH: '/srv/ssd/Bookshelf/Audiobooks',
        PATH_MAPPINGS: '/audiobooks:/srv/ssd/Bookshelf/Audiobooks,/summaries:/srv/ssd/Bookshelf/Summaries'
      }
    }
  ]
};
