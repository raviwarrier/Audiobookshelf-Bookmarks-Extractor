module.exports = {
  apps: [
    {
      name: 'abs-extractor-web',
      script: 'dist/server.cjs',
      cwd: './',
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
      script: 'main.py',
      cwd: './',
      interpreter: require('fs').existsSync('./venv/bin/python3') ? './venv/bin/python3' : 'python3',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      env: {
        PORT: 8000
      }
    }
  ]
};
