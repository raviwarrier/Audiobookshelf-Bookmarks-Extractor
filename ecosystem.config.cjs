const path = require('path');
const fs = require('fs');

// Allow overriding the installation directory via ABS_EXTRACTOR_DIR or default to this directory
const appDir = process.env.ABS_EXTRACTOR_DIR || __dirname;

// Attempt to read .env file if present in app directory
const envPath = path.join(appDir, '.env');
if (fs.existsSync(envPath)) {
  try {
    require('dotenv').config({ path: envPath });
  } catch {
    const lines = fs.readFileSync(envPath, 'utf8').split('\n');
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
        const [k, ...v] = trimmed.split('=');
        const key = k.trim();
        const val = v.join('=').trim().replace(/^['"]|['"]$/g, '');
        if (!process.env[key]) process.env[key] = val;
      }
    }
  }
}

// Detect python virtual environment inside the app directory or fallback to system python
const venvCandidates = [
  path.join(appDir, 'venv', 'bin', 'python3'),
  path.join(appDir, '.venv', 'bin', 'python3'),
  path.join(appDir, 'venv', 'bin', 'python'),
];
const detectedPython = venvCandidates.find(p => fs.existsSync(p));
const pythonInterpreter = detectedPython || 'python3';

module.exports = {
  apps: [
    {
      name: 'abs-extractor-web',
      cwd: appDir,
      script: path.join(appDir, 'dist', 'server.cjs'),
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'production',
        PORT: process.env.PORT || 13379
      }
    },
    {
      name: 'abs-extractor-sidecar',
      cwd: appDir,
      script: path.join(appDir, 'main.py'),
      interpreter: pythonInterpreter,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        PORT: process.env.SIDECAR_PORT || 13380,
        SIDECAR_PORT: process.env.SIDECAR_PORT || 13380,
        RELOAD: 'false',
        ABS_TARGET_SERVER: process.env.ABS_TARGET_SERVER || process.env.ABS_SERVER_URL || 'http://localhost:13378',
        ABS_SERVER_URL: process.env.ABS_TARGET_SERVER || process.env.ABS_SERVER_URL || 'http://localhost:13378',
        VOLUME_DIR: process.env.VOLUME_DIR || process.env.SNIPPETS_DIR || '/data'
      }
    }
  ]
};
