// ==============================================================================
// PM2 Ecosystem Configuration for Audiobookshelf Bookmarks Extractor
// ==============================================================================
// Instructions:
// 1. Set APP_DIR to the directory where this repository is installed.
//    Example: '/srv/ssd/Appdata/local/Audiobookshelf-Bookmarks-Extractor'
// 2. Set PYTHON_PATH to your virtual environment's python3 or system 'python3'.
//    Example: '/srv/ssd/Appdata/local/Audiobookshelf-Bookmarks-Extractor/venv/bin/python3'
// 3. Set VOLUME_DIR to where audio clips and transcripts should be saved.
//    Example: '/srv/ssd/Appdata/local/bookmarks'
// 4. Set ABS_TARGET_SERVER to your Audiobookshelf server URL.
//    Example: 'http://localhost:13378'
// ==============================================================================

// --- Configure your installation paths here ---
const APP_DIR = '/srv/ssd/Appdata/local/Audiobookshelf-Bookmarks-Extractor'; //path to where you have installed the app
const PYTHON_PATH = `python3`; // Set to 'python3' if not using a venv

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
        VOLUME_DIR: '/srv/ssd/Bookshelf/advplyr-bookshelf/bookmarks' // Output directory for bookmarks
      }
    }
  ]
};
