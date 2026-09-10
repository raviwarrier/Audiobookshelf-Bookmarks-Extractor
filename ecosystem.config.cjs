const path = require('path');
const fs = require('fs');

const appDir = __dirname;
const venvPython = path.join(appDir, 'venv', 'bin', 'python3');
const pythonInterpreter = fs.existsSync(venvPython) ? venvPython : 'python3';

module.exports = {
  apps: [
    {
      name: 'abs-extractor-web',
      script: path.join(appDir, 'dist', 'server.cjs'),
      cwd: appDir,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '500M',
      env: {
        NODE_ENV: 'production',
        PORT: 13379
      }
    },
    {
      name: 'abs-extractor-sidecar',
      script: path.join(appDir, 'main.py'),
      cwd: appDir,
      interpreter: pythonInterpreter,
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        PORT: 13380,
        RELOAD: 'false'
      }
    }
  ]
};
