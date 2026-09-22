import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        configure: (proxy) => {
          // Without this the dev server answers a bare 500 for every /api call when
          // the backend is not running, which reads as a server bug rather than a
          // process that was never started.
          proxy.on('error', (error, _request, response) => {
            const reason = error.code || error.message
            if (typeof response?.writeHead !== 'function' || response.headersSent) {
              response?.destroy?.()
              return
            }
            response.writeHead(503, { 'Content-Type': 'application/json' })
            response.end(
              JSON.stringify({
                detail:
                  `Backend not reachable at ${API_TARGET} (${reason}). Start it with: ` +
                  '.venv/bin/python -m uvicorn main:app --app-dir backend --reload',
              }),
            )
          })
        },
      },
    },
  },
})
